from pathlib import Path

from devclaw.core.attachments import Attachment, attach_image_file, format_attachments_for_prompt


def test_attach_image_file_copies_image_into_pending_attachments(tmp_path: Path):
    source = tmp_path / "screen.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    attachment = attach_image_file(tmp_path, source, "button is clipped")

    assert attachment.media_type == "image/png"
    assert attachment.note == "button is clipped"
    assert attachment.path.startswith(".devclaw/attachments/pending/")
    copied = tmp_path / attachment.path
    assert copied.exists()
    assert copied.read_bytes() == source.read_bytes()


def test_format_attachments_for_prompt_adds_reviewable_image_context():
    context = format_attachments_for_prompt(
        [
            Attachment(
                path=".devclaw/attachments/pending/screen.png",
                media_type="image/png",
                note="right panel is clipped",
                source="clipboard",
            )
        ]
    )

    assert "Attached screenshots" in context
    assert ".devclaw/attachments/pending/screen.png" in context
    assert "right panel is clipped" in context
