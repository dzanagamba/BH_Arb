"""One raw team-name key, shared by the gate, the ledger and the review UI."""

from __future__ import annotations

import engine.certainty as certainty_module
import engine.mapping_evidence as mapping_module
from engine.certainty import CertaintyGate
from engine.mapping_evidence import _raw_key, team_alias_key
from engine.name_keys import raw_team_key


def test_diacritics_and_punctuation_fold_to_the_same_key():
    assert raw_team_key("Bodø/Glimt") == raw_team_key("Bodo Glimt")
    assert raw_team_key("Wingate&Finchley") == raw_team_key("Wingate & Finchley")
    assert raw_team_key("Saint-Étienne") == raw_team_key("Saint Etienne")


def test_the_gate_delegates_to_the_shared_module():
    assert certainty_module.raw_team_key is raw_team_key
    for name in ("Bodø/Glimt", "Wingate&Finchley", "Saint-Étienne", "Man. Utd"):
        assert CertaintyGate._raw_team_key(name) == raw_team_key(name)


def test_the_ledger_delegates_to_the_shared_module():
    assert mapping_module.raw_team_key is raw_team_key
    assert _raw_key("Bodø/Glimt") == raw_team_key("Bodø/Glimt")
    assert team_alias_key("Bodø/Glimt", "Bodo Glimt") == "|".join(
        sorted((raw_team_key("Bodø/Glimt"), raw_team_key("Bodo Glimt")))
    )
