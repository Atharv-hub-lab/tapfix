from app.llm.solution_provider import _select_siis_supported_candidate


def test_smart_switch_siis_does_not_match_secure_folder_autosync():
    siis = """title=Transfer Secure folder with Smart Switch
content=Use Smart Switch to transfer data between Galaxy devices and scan the QR code."""

    candidates = [
        {
            "id": "DL-0027",
            "description": "Disables auto sync of Secure Folder data via device Settings on the device.",
            "message": "Disable Auto-Sync",
            "qna_description": (
                "Automatically syncs Secure Folder data to keep your private "
                "information backed up."
            ),
        }
    ]

    assert _select_siis_supported_candidate(siis, candidates) is None
