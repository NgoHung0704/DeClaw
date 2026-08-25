"""The development question set: French business documents we wrote ourselves.

Deliberately self-authored, and therefore deliberately NOT the number that
matters. It is the set we may iterate against; ``heldout.py`` is the one we may
not. The sanitizer scored 91.7% on its own corpus and 53.3% on external data —
that 38-point gap is why these two files exist separately.

The corpus is generated rather than committed as binaries, so it is diffable in
review and regenerable on any machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

from declaw.documents.benchmark import BenchmarkQuestion


@dataclass(frozen=True, slots=True)
class SyntheticDocument:
    """One generated document: its filename and its paragraphs."""

    name: str
    paragraphs: tuple[str, ...]


SYNTHETIC_DOCUMENTS: tuple[SyntheticDocument, ...] = (
    SyntheticDocument(
        name="contrat-prestation.pdf",
        paragraphs=(
            "CONTRAT DE PRESTATION DE SERVICES",
            "Entre MARTIN CONSEIL, ci-apres le Prestataire, et DUPONT SARL, "
            "ci-apres le Client.",
            "ARTICLE 7 - RESILIATION",
            "Chaque partie peut resilier le present contrat moyennant un preavis "
            "de trois mois notifie par lettre recommandee.",
            "ARTICLE 8 - CONFIDENTIALITE",
            "Les parties gardent confidentielles les informations echangees "
            "pendant une duree de cinq ans apres la fin du contrat.",
            "ARTICLE 9 - LOI APPLICABLE",
            "Le present contrat est soumis au droit francais et tout litige "
            "releve du tribunal de commerce de Lyon.",
        ),
    ),
    SyntheticDocument(
        name="facture-2024-03.txt",
        paragraphs=(
            "FACTURE N 2024-03-017",
            "Emise le 15 mars 2024 par MARTIN CONSEIL a l'attention de DUPONT SARL.",
            "Prestation de conseil en organisation : 12000 euros HT.",
            "Formation des equipes : 3500 euros HT.",
            "Total a regler : 15500 euros HT, soit 18600 euros TTC.",
            "Le reglement intervient a trente jours fin de mois.",
        ),
    ),
    SyntheticDocument(
        name="compte-rendu-reunion.txt",
        paragraphs=(
            "COMPTE RENDU DE REUNION",
            "Reunion du 12 mars 2024, en presence de Madame Martin et Monsieur Dupont.",
            "Le budget formation est porte a 3500 euros pour l'exercice en cours.",
            "La prochaine revue de contrat est fixee au 30 juin 2024.",
            "Il est decide de reporter le recrutement du second consultant.",
        ),
    ),
    SyntheticDocument(
        name="lettre-resiliation.txt",
        paragraphs=(
            "Objet : resiliation du contrat de prestation",
            "Lyon, le 2 avril 2024",
            "Madame, Monsieur,",
            "Par la presente, nous vous informons de notre decision de resilier le "
            "contrat signe le 4 janvier 2023, conformement a son article 7.",
            "La resiliation prendra effet le 2 juillet 2024, au terme du preavis "
            "contractuel de trois mois.",
            "Nous restons a votre disposition pour organiser la transition.",
        ),
    ),
)

SYNTHETIC_QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    BenchmarkQuestion(
        question="Quel est le delai de preavis pour resilier le contrat ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="preavis de trois mois",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Combien de temps dure l'obligation de confidentialite ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="duree de cinq ans",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel tribunal est competent en cas de litige ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="tribunal de commerce de Lyon",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Qui sont les parties au contrat de prestation ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="MARTIN CONSEIL",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le montant total de la facture de mars ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="15500 euros HT",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Combien coute la prestation de conseil en organisation ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="12000 euros HT",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le delai de reglement de la facture ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="trente jours fin de mois",
        language="fr",
    ),
    BenchmarkQuestion(
        question="A combien s'eleve le budget formation ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="3500 euros",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quand a lieu la prochaine revue de contrat ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="30 juin 2024",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Qui etait present a la reunion de mars ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="Madame Martin",
        language="fr",
    ),
    BenchmarkQuestion(
        question="A quelle date la resiliation prend-elle effet ?",
        expected_path="lettre-resiliation.txt",
        expected_snippet="2 juillet 2024",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quand le contrat resilie avait-il ete signe ?",
        expected_path="lettre-resiliation.txt",
        expected_snippet="4 janvier 2023",
        language="fr",
    ),
)


def write_synthetic_corpus(folder: Path) -> list[Path]:
    """Generate the development corpus into ``folder``. Reproducible."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for document in SYNTHETIC_DOCUMENTS:
        path = folder / document.name
        if path.suffix == ".pdf":
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("helvetica", size=12)
            pdf.add_page()
            for paragraph in document.paragraphs:
                # w=0 raises FPDFException; an explicit width is required.
                pdf.multi_cell(w=180, h=8, text=paragraph)
            path.write_bytes(bytes(pdf.output()))
        else:
            path.write_text("\n\n".join(document.paragraphs), encoding="utf-8")
        written.append(path)
    return written
