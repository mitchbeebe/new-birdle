import asyncio
import json
import re
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from django.core.management.base import BaseCommand
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from birdle.models import Bird

MAX_TOKENS = 512

# The model provider is abstracted via LangChain's with_structured_output, so
# switching providers later should mainly mean swapping the ChatOpenAI(...)
# constructor below (e.g. for ChatAnthropic(...)) plus this model id.
HINT_MODEL = "gpt-5.6-luna"


class Riddles(BaseModel):
    vague: str = Field(
        ...,
        description=(
            "A very vague riddle that could apply to many birds. "
            "Hint only at behavior or habitat rather than appearance, "
            "family, or name origin. "
            "Two short clauses of similar length ending in words that "
            "truly rhyme (same end sound, not just similar spelling)."
        ),
        examples=[("I strut where people meet the street; seeking crumbs with nimble feet.")],
    )
    general: str = Field(
        ...,
        description=(
            "A more general riddle that narrows down the possibilities. "
            "Explicitly reference a relative or shared family trait (e.g. "
            "'my cousin the ...') without using words that give away the "
            "name. "
            "Two short clauses of similar length ending in words that "
            "truly rhyme (same end sound, not just similar spelling)."
        ),
        examples=[("In my family, my cousin the dove; perched on buildings, cooing above.")],
    )
    specific: str = Field(
        ...,
        description=(
            "A specific riddle that should make the bird easily identifiable. "
            "Hint at how the bird got its name (its etymology), but DO NOT "
            "use words that give away the name. "
            "Two short clauses of similar length ending in words that "
            "truly rhyme (same end sound, not just similar spelling)."
        ),
        examples=[("Mountains and cliffs, my name implies; famous in NYC, my habitat belies.")],
    )


def get_offlimit_words(bird):
    raw_offlimit_words = (
        re.split(r"[\s-]+", bird.name.lower())
        + re.split(r"[\s-]+", bird.order.lower())
        + re.split(r"[\s-]+", bird.family.lower())
        + re.split(r"[\s-]+", bird.genus.lower())
    )
    offlimit_words = []
    for word in raw_offlimit_words:
        no_possessive = re.sub(r"[’']s\b", "", word)
        cleaned = re.sub(r"[^a-z0-9]", "", no_possessive)
        if cleaned:
            offlimit_words.append(cleaned)
    return sorted(set(offlimit_words))


def build_riddle_prompt(bird):
    forbidden_terms = get_offlimit_words(bird)

    instructions = (
        "You are a rhyming ornothologist for a bird-guessing game. "
        "Generate three riddles: vague, general, specific.\n\n"
        "Priority rules (highest to lowest):\n"
        "1) Safety constraint: Never output any forbidden term\n"
        "2) Riddle structure: Return exactly three riddles\n"
        "3) Rhyme: Riddles contain two clauses, separated by a semicolon, "
        "whose final words truly rhyme (same end sound, e.g. 'street'/"
        "'feet' — not just similar spelling, e.g. NOT 'suit'/'greet')\n"
        "4) Riddle length: Keep it under 20 words, with both clauses "
        "close to the same length\n\n"
        "Forbidden-term rule:\n"
        "- A riddle is invalid if it contains any forbidden term in any form:\n"
        "  exact word, plural/possessive, hyphenated form, or as part of a "
        "compound (including '-like').\n"
        "- Before producing final output, silently check each riddle for: "
        "(a) zero forbidden-term violations, (b) a true end rhyme between "
        "the two clauses, (c) balanced clause length. Rewrite any riddle "
        "that fails any of these checks.\n"
        "- Do not mention the forbidden list or say that words are forbidden.\n\n"
        "Riddle intent (each riddle should narrow down the bird further "
        "than the last):\n"
        "- vague: broad behavior/habitat clue that applies to many birds; "
        "no family or name hints\n"
        "- general: explicitly reference a relative or shared family trait "
        "(e.g. 'my cousin the ...'), without forbidden terms\n"
        "- specific: hint at the name's etymology, without forbidden "
        "terms\n\n"
        "Output format:\n"
        "Return only the JSON object for the required schema fields: "
        "vague, general, specific."
    )
    input_str = (
        "TARGET\n"
        f"- common_name: {bird.name}\n"
        f"- scientific_name: {bird.scientific_name}\n"
        f"- order: {bird.order}\n"
        f"- family: {bird.family}\n"
        f"- genus: {bird.genus}\n\n"
        "FORBIDDEN_TERMS_JSON\n"
        f"{json.dumps(forbidden_terms)}\n"
    )
    return instructions, input_str


def build_riddle_messages(bird):
    instructions, input_str = build_riddle_prompt(bird)
    return [("system", instructions), ("human", input_str)]


def build_riddle_llm():
    # temperature=None omits the param entirely - HINT_MODEL rejects an
    # explicit temperature value ("Unsupported parameter: 'temperature'").
    # reasoning_effort="none" disables this reasoning model's hidden
    # reasoning tokens, which otherwise silently eat the whole max_tokens
    # budget before any riddle text is produced.
    llm = ChatOpenAI(
        model=HINT_MODEL,
        temperature=None,
        max_completion_tokens=MAX_TOKENS,
        reasoning_effort="none",
    )
    return llm.with_structured_output(Riddles)


def generate_riddles(llm, bird):
    riddles = llm.invoke(build_riddle_messages(bird))
    if not isinstance(riddles, Riddles):
        raise ValueError("Expected output to be of type Riddles")
    return riddles


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Command(BaseCommand):
    help = "Generate riddle hints for birds and persist them to the database"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.console = Console()

    def add_arguments(self, parser):
        parser.add_argument(
            "--species-code", type=str, help="Only generate riddles for this species code"
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Regenerate riddles even for birds that already have them",
        )
        parser.add_argument("--limit", type=int, help="Only process this many birds")
        parser.add_argument(
            "--batch",
            action="store_true",
            help="Generate riddles concurrently (via LangChain's .batch()) instead of one by one",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Max number of birds processed concurrently at once (default: 50)",
        )
        parser.add_argument(
            "--print",
            action="store_true",
            dest="print_only",
            help="Generate and print riddles for the selected bird(s) without persisting them",
        )

    def handle(self, *args, **options):
        load_dotenv("birdle/.env")
        llm = build_riddle_llm()

        birds = Bird.objects.all()
        if options["species_code"]:
            birds = birds.filter(species_code=options["species_code"])
        if not options["overwrite"]:
            birds = birds.filter(hint_vague="")
        if options["limit"]:
            birds = birds[: options["limit"]]

        total = birds.count()
        if total == 0:
            self.console.print("[yellow]No birds to process.[/yellow]")
            return

        if options["print_only"]:
            self.handle_print(llm, birds)
        elif options["batch"]:
            self.handle_batch(llm, list(birds), options["batch_size"])
        else:
            self.handle_sync(llm, birds, total)

    def print_riddles(self, bird, riddles):
        self.console.print(
            Panel(
                f"[bold]vague:[/bold] {riddles.vague}\n"
                f"[bold]general:[/bold] {riddles.general}\n"
                f"[bold]specific:[/bold] {riddles.specific}",
                title=f"{bird.name} ({bird.species_code})",
            )
        )

    def handle_print(self, llm, birds):
        for bird in birds:
            try:
                riddles = generate_riddles(llm, bird)
            except Exception as e:
                self.console.print(
                    f"[bold red]Error[/bold red] generating riddles for "
                    f"{bird.name} ({bird.species_code}): {e}"
                )
                continue
            self.print_riddles(bird, riddles)

    def handle_sync(self, llm, birds, total):
        success_count = 0
        error_count = 0
        with self.console.status(
            f"[bold green]Generating riddles for {total} bird(s)...[/bold green]"
        ) as status:
            for i, bird in enumerate(birds, start=1):
                status.update(
                    f"[bold green]({i}/{total}) Generating riddles for {bird.name}...[/bold green]"
                )
                try:
                    riddles = generate_riddles(llm, bird)
                except Exception as e:
                    error_count += 1
                    self.console.print(
                        f"[bold red]Error[/bold red] generating riddles for "
                        f"{bird.name} ({bird.species_code}): {e}"
                    )
                    continue

                Bird.objects.filter(pk=bird.pk).update(
                    hint_vague=riddles.vague,
                    hint_general=riddles.general,
                    hint_specific=riddles.specific,
                )
                success_count += 1

        self.console.print(
            f"[bold green]Done.[/bold green] {success_count} succeeded, {error_count} failed."
        )

    def handle_batch(self, llm, birds, batch_size):
        success_count = 0
        error_count = 0

        for i, chunk in enumerate(chunked(birds, batch_size), start=1):
            self.console.print(
                f"[bold green]Processing chunk {i} ({len(chunk)} bird(s))...[/bold green]"
            )
            inputs = [build_riddle_messages(bird) for bird in chunk]
            results = asyncio.run(
                llm.abatch(inputs, config={"max_concurrency": batch_size}, return_exceptions=True)
            )

            for bird, result in zip(chunk, results):
                if isinstance(result, Exception) or not isinstance(result, Riddles):
                    error_count += 1
                    self.console.print(
                        f"[bold red]Error[/bold red] generating riddles for "
                        f"{bird.name} ({bird.species_code}): {result}"
                    )
                    continue

                Bird.objects.filter(pk=bird.pk).update(
                    hint_vague=result.vague,
                    hint_general=result.general,
                    hint_specific=result.specific,
                )
                success_count += 1

        self.console.print(
            f"[bold green]Done.[/bold green] {success_count} succeeded, {error_count} failed."
        )
