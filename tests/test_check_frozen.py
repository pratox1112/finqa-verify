from check_frozen import BASE_CONFIG, PROMPT_MANIFEST, find_violations

SCHEMAS = "src/finqa/schemas.py"
SPLITS = "data/splits.json"
PROMPT = "src/finqa/prompts/rag_v1.md"

BASE_YAML = "model:\n  id: qwen\n  temperature: 0\nretrieval:\n  top_k: 5\n"


def readers(base: dict[str, str], head: dict[str, str]):
    return base.get, head.get


def test_modifying_schemas_is_a_violation() -> None:
    base, head = readers({SCHEMAS: "old"}, {SCHEMAS: "new"})
    assert find_violations([SCHEMAS], base, head) == [f"{SCHEMAS} is frozen"]


def test_creating_a_frozen_file_is_allowed() -> None:
    base, head = readers({}, {SCHEMAS: "new"})
    assert find_violations([SCHEMAS], base, head) == []


def test_deleting_splits_is_a_violation() -> None:
    base, head = readers({SPLITS: "{}"}, {})
    assert find_violations([SPLITS], base, head) == [f"{SPLITS} is frozen"]


def test_unrelated_change_is_allowed() -> None:
    base, head = readers({"README.md": "a"}, {"README.md": "b"})
    assert find_violations(["README.md"], base, head) == []


def test_base_config_non_model_change_is_allowed() -> None:
    new = BASE_YAML.replace("top_k: 5", "top_k: 8")
    base, head = readers({BASE_CONFIG: BASE_YAML}, {BASE_CONFIG: new})
    assert find_violations([BASE_CONFIG], base, head) == []


def test_base_config_model_change_is_a_violation() -> None:
    new = BASE_YAML.replace("temperature: 0", "temperature: 0.7")
    base, head = readers({BASE_CONFIG: BASE_YAML}, {BASE_CONFIG: new})
    assert find_violations([BASE_CONFIG], base, head) == [
        f"{BASE_CONFIG}: model settings are frozen"
    ]


def test_prompt_listed_in_manifest_is_frozen() -> None:
    manifest = "# frozen prompts\nrag_v1.md  # approved 2026-11-10\n"
    base, head = readers({PROMPT_MANIFEST: manifest, PROMPT: "old"}, {PROMPT: "new"})
    assert find_violations([PROMPT], base, head) == [f"{PROMPT} is frozen"]


def test_prompt_not_in_manifest_is_editable() -> None:
    base, head = readers({PROMPT: "old"}, {PROMPT: "new"})
    assert find_violations([PROMPT], base, head) == []


def test_editing_the_manifest_is_a_violation() -> None:
    base, head = readers({PROMPT_MANIFEST: "rag_v1.md\n"}, {PROMPT_MANIFEST: ""})
    assert find_violations([PROMPT_MANIFEST], base, head) == [f"{PROMPT_MANIFEST} is frozen"]
