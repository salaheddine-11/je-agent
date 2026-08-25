"""Report label translations (Feature: language selection).

Labels only — numbers, rule names, statuses, and data stay verbatim so the
report remains deterministic and audit-traceable. The LLM narrative is generated
in the engagement's language separately; these strings cover the fixed template.
"""

REPORT_LABELS = {
    "en": {
        "eyebrow": "Journal Entry Testing · ISA 240 / AS 2401",
        "sub": ("journal-entry extract — risk assessment, AI-assisted triage "
                "and auditor review workpaper"),
        "eng_summary": "Engagement summary",
        "period": "Period under review",
        "source": "Source system / extract",
        "population": "Population tested",
        "materiality": "Materiality",
        "flagged": "Flagged for review",
        "benford": "Benford conformity (C2, informational)",
        "auditor": "Auditor",
        "status": "Report status",
        "confidential": ("Confidential. Prepared with JE Agent — deterministic rules, "
                         "LLM-assisted triage, human judgment. Engagement workpaper; "
                         "see limitations before relying on its contents."),
        "generated": "Generated",
        "lines": "lines",
        "documents": "documents",
        "universe_of": "universe of",
        "inspect": "inspect",
        "accepted": "accepted",
        "override": "override",
        "overall": "overall",
        "performance": "performance",
        "hash_chained": "decisions hash-chained and",
        "verified": "verified",
        "broken": "BROKEN",
        "all_gates": ("All finalize gates passed (review completeness, procedure "
                      "completeness, citation validity, limitation acceptance)."),
        "draft_gates": "Run not yet finalized — gates pending.",
        "finalized": "FINALIZED",
        "draft": "DRAFT",
        "audit_report": "Audit Report",
        "extract_pe": "extract · period end",
        "materiality_short": "materiality",
        "reviewer": "reviewer",
    },
    "fr": {
        "eyebrow": "Test des écritures de journal · ISA 240 / AS 2401",
        "sub": ("extrait des écritures de journal — évaluation des risques, triage "
                "assisté par IA et classeur de révision de l'auditeur"),
        "eng_summary": "Résumé de l'engagement",
        "period": "Période examinée",
        "source": "Système source / extrait",
        "population": "Population testée",
        "materiality": "Matérialité",
        "flagged": "Écritures signalées",
        "benford": "Conformité de Benford (C2, informatif)",
        "auditor": "Auditeur",
        "status": "Statut du rapport",
        "confidential": ("Confidentiel. Préparé avec JE Agent — règles déterministes, "
                         "triage assisté par IA, jugement humain. Classeur de travail ; "
                         "voir les limites avant de vous y fier."),
        "generated": "Généré le",
        "lines": "lignes",
        "documents": "documents",
        "universe_of": "univers de",
        "inspect": "examen",
        "accepted": "acceptées",
        "override": "remplacées",
        "overall": "globale",
        "performance": "performance",
        "hash_chained": "décisions chaînées par hachage et",
        "verified": "vérifiées",
        "broken": "ROMPU",
        "all_gates": ("Toutes les portes de finalisation sont passées (complétude de la "
                      "révision, complétude des procédures, validité des citations, "
                      "acceptation des limites)."),
        "draft_gates": "Essai non encore finalisé — portes en attente.",
        "finalized": "FINALISÉ",
        "draft": "BROUILLON",
        "audit_report": "Rapport d'audit",
        "extract_pe": "extrait · fin de période",
        "materiality_short": "matérialité",
        "reviewer": "réviseur",
    },
}


def labels(lang: str) -> dict:
    return REPORT_LABELS.get(lang, REPORT_LABELS["en"])
