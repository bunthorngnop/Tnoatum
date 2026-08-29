from pathlib import Path


def test_gitignore_protects_secrets_databases_backups_and_logs() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "credentials*.json", "*.sqlite3", "backups/", "*.log"):
        assert pattern in text

