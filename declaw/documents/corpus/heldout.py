"""The held-out question set: real EU legal texts nobody here wrote.

TWO RULES, and they are the entire value of this file:

1. **Never quote these documents or questions in a prompt.** The moment their
   text appears in a prompt, the number stops measuring generalisation.
2. **Never tune against an individual failure here.** Fix the concept in the
   retrieval pipeline, then re-measure. Otherwise this silently becomes a
   second training set — which is exactly how the sanitizer ended up scoring
   91.7% on its own corpus and 53.3% on external data.

The QUESTIONS are written by reading the documents; the DOCUMENTS are external
and unmodified in substance, which is the property that matters. Every
``expected_snippet`` below was copied verbatim out of the committed file rather
than recalled, and ``test_documents_corpus.py`` fails if one drifts.
"""

from __future__ import annotations

from pathlib import Path

from declaw.documents.benchmark import BenchmarkQuestion

HELDOUT_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "documents" / "heldout"
)

HELDOUT_QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    BenchmarkQuestion(
        question="Sous quel délai le responsable du traitement doit-il répondre à une demande ?",
        expected_path="rgpd-2016-679.txt",
        expected_snippet="au plus tard dans un délai d'un mois",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le montant maximal des amendes liées au chiffre d'affaires ?",
        expected_path="rgpd-2016-679.txt",
        expected_snippet="10 000 000 EUR",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel pourcentage du chiffre d'affaires mondial peut être exigé ?",
        expected_path="rgpd-2016-679.txt",
        expected_snippet="chiffre d'affaires annuel mondial total",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Qui donne des indications sur les opérations de traitement ?",
        expected_path="rgpd-2016-679.txt",
        expected_snippet="délégué à la protection des données",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quelles exceptions obligatoires la directive sur le droit d'auteur instaure-t-elle ?",
        expected_path="directive-2019-790-droit-auteur.txt",
        expected_snippet="fouille de textes et de données",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quels nouveaux services en ligne ont émergé pour la presse ?",
        expected_path="directive-2019-790-droit-auteur.txt",
        expected_snippet="agrégateurs d'informations",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le délai de rétractation pour un contrat de service ?",
        expected_path="directive-2011-83-consommateurs.txt",
        expected_snippet="quatorze jours",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Sur quoi porte l'harmonisation complète de l'information des consommateurs ?",
        expected_path="directive-2011-83-consommateurs.txt",
        expected_snippet="droit de rétractation",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Comment les seuils de l'AMP sont-ils exprimés ?",
        expected_path="directive-2014-24-marches-publics.txt",
        expected_snippet="droits de tirage spéciaux",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quelle notion prépondérante est utilisée pour retenir une offre ?",
        expected_path="directive-2014-24-marches-publics.txt",
        expected_snippet="la plus avantageuse",
        language="fr",
    ),
)
