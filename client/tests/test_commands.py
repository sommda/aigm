from aigm_client.commands import parse_command


def test_not_a_command():
    assert parse_command("I attack") is None


def test_basic_and_flags():
    c = parse_command("/save my-game --overwrite")
    assert (c.name, c.arg, "overwrite" in c.flags) == ("save", "my-game", True)
    assert parse_command("/new").name == "new"
    assert parse_command("/load").arg is None


def test_unknown():
    c = parse_command("/frobnicate x")
    assert c.name == "unknown" and c.arg == "frobnicate"
    assert parse_command("/").name == "unknown"
