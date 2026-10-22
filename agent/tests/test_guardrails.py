from agent import guardrails


def test_forbidden_vocabulary():
    assert guardrails.check_text("Ta récupération baisse, ta charge augmente.") == []
    assert guardrails.check_text("On détecte du stress cette semaine")
    assert guardrails.check_text("Ton humeur a changé")
    assert guardrails.check_text("Tes émotions comptent")          # accents normalisés
    assert guardrails.check_text("Tu fais un burn-out")
    assert guardrails.check_text("Diagnostic : épuisement")


def test_block_must_be_private_and_named_occupe():
    ok = {"kind": "calendar_block", "payload": {"start": "2026-10-26T12:30:00", "end": "2026-10-26T13:30:00",
                                                "title": "Occupé", "visibility": "private", "purpose": "dejeuner"}}
    assert guardrails.check_plan([ok]) == []
    leak = {"kind": "calendar_block", "payload": {**ok["payload"], "title": "Séance psy"}}
    assert guardrails.check_plan([leak])


def test_orientation_required_when_many_red_days():
    assert guardrails.check_orientation(3, "Protège tes déjeuners.")
    assert guardrails.check_orientation(3, "Le médecin du travail peut t'aider.") == []
    assert guardrails.check_orientation(1, "Protège tes déjeuners.") == []


def test_hr_text_never_cites_small_groups():
    assert guardrails.check_hr_text("3 personnes de l'équipe M&A sont en dette")
    assert guardrails.check_hr_text("La majorité de l'équipe est en dette de récupération") == []
