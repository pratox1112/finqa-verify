from sync_if_lock_changed import NULL_SHA, lock_changed


def diff_returning(output: str | None):
    calls: list[tuple[str, str]] = []

    def diff(from_ref: str, to_ref: str) -> str | None:
        calls.append((from_ref, to_ref))
        return output

    return diff, calls


def test_lock_changed_on_checkout() -> None:
    diff, calls = diff_returning("uv.lock\n")
    env = {
        "PRE_COMMIT_FROM_REF": "aaa",
        "PRE_COMMIT_TO_REF": "bbb",
        "PRE_COMMIT_CHECKOUT_TYPE": "1",
    }
    assert lock_changed(env, diff)
    assert calls == [("aaa", "bbb")]


def test_lock_unchanged() -> None:
    diff, _ = diff_returning("")
    assert not lock_changed({"PRE_COMMIT_FROM_REF": "aaa", "PRE_COMMIT_TO_REF": "bbb"}, diff)


def test_post_merge_compares_orig_head_to_head() -> None:
    diff, calls = diff_returning("uv.lock\n")
    assert lock_changed({}, diff)
    assert calls == [("ORIG_HEAD", "HEAD")]


def test_file_checkout_is_ignored() -> None:
    diff, calls = diff_returning("uv.lock\n")
    assert not lock_changed({"PRE_COMMIT_CHECKOUT_TYPE": "0"}, diff)
    assert calls == []


def test_fresh_clone_syncs() -> None:
    diff, _ = diff_returning("")
    assert lock_changed({"PRE_COMMIT_FROM_REF": NULL_SHA, "PRE_COMMIT_TO_REF": "bbb"}, diff)


def test_git_failure_syncs_to_be_safe() -> None:
    diff, _ = diff_returning(None)
    assert lock_changed({}, diff)
