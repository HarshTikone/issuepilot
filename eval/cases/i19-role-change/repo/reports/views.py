from reports.export import export_rows


def download(rows):
    return {"content_type": "text/csv", "body": export_rows(rows)}
