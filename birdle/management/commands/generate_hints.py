import json
import os
import re
import time
from anthropic import Anthropic
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table
from birdle.models import Bird

RIDDLE_TOOL_NAME = "submit_riddles"
MAX_TOKENS = 512

HINT_MODEL = "claude-haiku-4-5-20251001"


class Riddles(BaseModel):
    vague: str = Field(
        ...,
        description=(
            "A very vague riddle that could apply to many birds. "
            "Hint at behavior or habitat rather than appearance."
        ),
        examples=[("I strut where people meet the street, seeking crumbs with nimble feet.")],
    )
    general: str = Field(
        ...,
        description=(
            "A more general riddle that narrows down the possibilities. "
            "Hint at family-level characteristics or similarities to other "
            "birds without using words that give away the name."
        ),
    )
    specific: str = Field(
        ...,
        description=(
            "A specific riddle that should make the bird easily identifiable. "
            "You may hint at how the bird got its name, but DO NOT use words "
            "that give away the name."
        ),
        examples=[
            (
                "My name comes from a churchman's robe; "
                "Spot me in the backyard, the birdfeeders I probe."
            )
        ],
    )


def get_offlimit_words(bird):
    raw_offlimit_words = (
        bird.name.lower().split()
        + bird.order.lower().split()
        + bird.family.lower().split()
        + bird.genus.lower().split()
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
        "3) Style: Riddles contain two clauses that rhyme and are "
        "separated by a semicolon\n\n"
        "Forbidden-term rule:\n"
        "- A riddle is invalid if it contains any forbidden term in any form:\n"
        "  exact word, plural/possessive, hyphenated form, or as part of a "
        "compound (including '-like').\n"
        "- Before producing final output, silently check all three riddles against "
        "the forbidden list and rewrite until zero violations.\n"
        "- Do not mention the forbidden list or say that words are forbidden.\n\n"
        "Riddle intent:\n"
        "- vague: broad behavior/habitat clue that applies to many birds\n"
        "- general: hint at family-level traits or similarity to other birds, "
        "without forbidden terms\n"
        "- specific: strong clue, hint at naming origin, without forbidden "
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


def build_riddle_tool():
    return {
        "name": RIDDLE_TOOL_NAME,
        "description": "Submit the three generated riddles.",
        "input_schema": Riddles.model_json_schema(),
    }


def parse_riddles_from_content(content):
    tool_use = next(block for block in content if block.type == "tool_use")
    return Riddles.model_validate(tool_use.input)


def generate_riddles(client, bird):
    instructions, input_str = build_riddle_prompt(bird)
    tool = build_riddle_tool()

    response = client.messages.create(
        model=HINT_MODEL,
        max_tokens=MAX_TOKENS,
        system=instructions,
        messages=[{"role": "user", "content": input_str}],
        tools=[tool],
        tool_choice={"type": "tool", "name": RIDDLE_TOOL_NAME},
    )
    return parse_riddles_from_content(response.content)


def build_batch_request(bird):
    instructions, input_str = build_riddle_prompt(bird)
    return {
        "custom_id": str(bird.pk),
        "params": {
            "model": HINT_MODEL,
            "max_tokens": MAX_TOKENS,
            "system": instructions,
            "messages": [{"role": "user", "content": input_str}],
            "tools": [build_riddle_tool()],
            "tool_choice": {"type": "tool", "name": RIDDLE_TOOL_NAME},
        },
    }


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def submit_batches(client, birds, batch_size, console):
    batches = []
    for chunk in chunked(birds, batch_size):
        requests = [build_batch_request(bird) for bird in chunk]
        batch = client.messages.batches.create(requests=requests)
        console.print(f"[bold blue]Submitted batch {batch.id}[/bold blue] ({len(chunk)} bird(s))")
        batches.append(batch)
    return batches


def poll_batches(client, batches, console, poll_interval=30):
    batches = {batch.id: batch for batch in batches}
    while True:
        for batch_id in list(batches):
            batches[batch_id] = client.messages.batches.retrieve(batch_id)

        table = Table(title="Batch status")
        table.add_column("Batch ID")
        table.add_column("Status")
        table.add_column("Succeeded")
        table.add_column("Errored")
        table.add_column("Expired")
        table.add_column("Canceled")
        for batch in batches.values():
            counts = batch.request_counts
            table.add_row(
                batch.id,
                batch.processing_status,
                str(counts.succeeded),
                str(counts.errored),
                str(counts.expired),
                str(counts.canceled),
            )
        console.print(table)

        if all(batch.processing_status == "ended" for batch in batches.values()):
            return list(batches.values())
        time.sleep(poll_interval)


def persist_batch_results(client, batch, console):
    success_count = 0
    error_count = 0

    for entry in client.messages.batches.results(batch.id):
        custom_id = entry.custom_id
        result = entry.result

        if result.type != "succeeded":
            error_count += 1
            console.print(
                f"[bold red]Error[/bold red] in batch {batch.id} for bird "
                f"pk={custom_id}: {result.type}"
            )
            continue

        try:
            riddles = parse_riddles_from_content(result.message.content)
        except Exception as e:
            error_count += 1
            console.print(f"[bold red]Error[/bold red] parsing result for bird pk={custom_id}: {e}")
            continue

        Bird.objects.filter(pk=int(custom_id)).update(
            hint_vague=riddles.vague,
            hint_general=riddles.general,
            hint_specific=riddles.specific,
        )
        success_count += 1

    return success_count, error_count


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
            help="Use the Anthropic Message Batches API instead of synchronous per-bird requests",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Max number of birds per submitted batch job (default: 5000)",
        )

    def handle(self, *args, **options):
        load_dotenv("birdle/.env")
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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

        if options["batch"]:
            self.handle_batch(client, list(birds), options["batch_size"])
        else:
            self.handle_sync(client, birds, total)

    def handle_sync(self, client, birds, total):
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
                    riddles = generate_riddles(client, bird)
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

    def handle_batch(self, client, birds, batch_size):
        batches = submit_batches(client, birds, batch_size, self.console)
        batches = poll_batches(client, batches, self.console)

        success_count = 0
        error_count = 0
        for batch in batches:
            batch_success, batch_error = persist_batch_results(client, batch, self.console)
            success_count += batch_success
            error_count += batch_error

        self.console.print(
            f"[bold green]Done.[/bold green] {success_count} succeeded, {error_count} failed."
        )
