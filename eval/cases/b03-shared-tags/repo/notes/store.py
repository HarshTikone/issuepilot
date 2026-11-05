from notes.tags import add_tag

NOTES = {}


def create_note(note_id, text, tag=None):
    note = {"id": note_id, "text": text}
    if tag:
        add_tag(note, tag)
    NOTES[note_id] = note
    return note
