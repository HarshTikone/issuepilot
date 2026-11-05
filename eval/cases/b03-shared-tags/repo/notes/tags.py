def add_tag(note, tag, tags=[]):
    tags.append(tag)
    note["tags"] = tags
    return note


def remove_tag(note, tag):
    note["tags"] = [t for t in note.get("tags", []) if t != tag]
    return note
