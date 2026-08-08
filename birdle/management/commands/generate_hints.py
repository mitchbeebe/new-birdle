import json
import os
import re
from dotenv import load_dotenv
from openai import OpenAI
from django.core.management.base import BaseCommand
from pydantic import BaseModel, Field
from rich.console import Console
from birdle.models import Bird

HINT_MODEL = "gpt-5.4-mini"


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


def generate_riddles(client, bird):
    forbidden_terms = get_offlimit_words(bird)

    response = client.responses.parse(
        model=HINT_MODEL,
        temperature=0,
        instructions=(
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
        ),
        input=(
            "TARGET\n"
            f"- common_name: {bird.name}\n"
            f"- scientific_name: {bird.scientific_name}\n"
            f"- order: {bird.order}\n"
            f"- family: {bird.family}\n"
            f"- genus: {bird.genus}\n\n"
            "FORBIDDEN_TERMS_JSON\n"
            f"{json.dumps(forbidden_terms)}\n"
        ),
        text_format=Riddles,
    )

    if not isinstance(response.output_parsed, Riddles):
        raise ValueError("Expected output to be of type Riddles")
    return response.output_parsed


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

    def handle(self, *args, **options):
        load_dotenv("birdle/.env")
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
