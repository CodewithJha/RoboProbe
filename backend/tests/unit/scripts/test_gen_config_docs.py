import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest
from pydantic import BaseModel, Field, SecretStr

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "gen_config_docs.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_config_docs", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


gen = _load_script()


class Inner(BaseModel):
    ratio: float = Field(default=0.5, description="A ratio | with pipe [0-1].")
    names: tuple[str, ...] = Field(default=("a", "b"), description="Names.")


class Tiny(BaseModel):
    env: Literal["local", "prod"] = Field(default="local", description="Environment.")
    path: Path = Field(default=Path("./data"), description="Data dir [path].")
    token: SecretStr | None = Field(default=None, description="Secret token.")
    enabled: bool = Field(default=True, description="Switch.")
    inner: Inner = Field(default_factory=Inner)


TINY_SECTIONS = (("4.1 Core", ("env", "path", "token", "enabled")), ("4.2 Inner", ("inner",)))
DOC = f"# Title\n\nprose before\n\n{gen.BEGIN_MARKER}\nstale\n{gen.END_MARKER}\n\nprose after\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / gen.DOC_FILE).write_text(DOC, encoding="utf-8")
    return tmp_path


def _run(repo: Path, *argv: str) -> int:
    return int(gen.main(list(argv), root_dir=repo, model=Tiny, sections=TINY_SECTIONS))


def test_iter_fields_flattens_nested_models() -> None:
    keys = [f.key for f in gen.iter_fields(Tiny)]
    assert keys == ["env", "path", "token", "enabled", "inner.ratio", "inner.names"]
    token = next(f for f in gen.iter_fields(Tiny) if f.key == "token")
    assert token.secret
    assert token.env_var == "ROBOPROBE_TOKEN"


def test_tables_render_every_key_and_escape_pipes() -> None:
    tables = gen.render_tables(Tiny, TINY_SECTIONS)
    assert "### 4.1 Core" in tables
    assert "### 4.2 Inner" in tables
    assert "| `inner.ratio` | float | `0.5` | `ROBOPROBE_INNER__RATIO` |" in tables
    assert "A ratio \\| with pipe" in tables
    assert "enum: `local` / `prod`" in tables
    assert f"| `token` | SecretStr? | {gen.NO_DEFAULT} |" in tables
    assert '`["a", "b"]`' in tables


def test_sections_must_cover_every_root_field() -> None:
    with pytest.raises(ValueError, match="every root field once"):
        gen.render_tables(Tiny, (("4.1 Core", ("env",)),))


def test_generation_preserves_prose_and_is_idempotent(repo: Path) -> None:
    assert _run(repo) == 0
    first = {p: (repo / p).read_text() for p in (gen.DOC_FILE, gen.ENV_FILE, gen.TOML_FILE)}
    doc = first[gen.DOC_FILE]
    assert doc.startswith("# Title\n\nprose before\n\n")
    assert doc.endswith(f"{gen.END_MARKER}\n\nprose after\n")
    assert "stale" not in doc
    assert _run(repo) == 0
    assert _run(repo, "--check") == 0
    assert first == {p: (repo / p).read_text() for p in first}


def test_check_fails_with_diff_on_drift(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(repo) == 0
    toml = repo / gen.TOML_FILE
    toml.write_text(toml.read_text().replace("# enabled = true", "# enabled = false"))
    capsys.readouterr()
    assert _run(repo, "--check") == 1
    err = capsys.readouterr().err
    assert "roboprobe.example.toml (generated)" in err
    assert "+# enabled = true" in err
    assert "1 generated file(s) stale" in err


def test_check_detects_description_change(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(repo) == 0
    changed = Inner.model_fields["ratio"].description
    monkeypatch.setattr(Inner.model_fields["ratio"], "description", f"{changed} Changed.")
    assert _run(repo, "--check") == 1


def test_templates_render_commented_defaults(repo: Path) -> None:
    assert _run(repo) == 0
    env = (repo / gen.ENV_FILE).read_text()
    toml = (repo / gen.TOML_FILE).read_text()
    assert "# ROBOPROBE_ENV=local" in env
    assert "# ROBOPROBE_ENABLED=true" in env
    assert "# ROBOPROBE_TOKEN=\n" in env
    assert '# ROBOPROBE_INNER__NAMES=["a", "b"]' in env
    assert "# ROBOPROBE_K2D_REPLICAS=2" in env
    assert '# path = "data"' in toml
    assert "[inner]\n" in toml
    assert '# names = ["a", "b"]' in toml
    assert "# token = ...  (secret: set ROBOPROBE_TOKEN instead)" in toml
    assert all(len(line) <= gen.COMMENT_WIDTH for line in (env + toml).splitlines())


def test_missing_markers_are_an_error() -> None:
    with pytest.raises(ValueError, match="markers"):
        gen.replace_block("no markers here", "x")


def test_repository_files_are_up_to_date() -> None:
    assert gen.main(["--check"]) == 0
