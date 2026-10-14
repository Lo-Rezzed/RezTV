from app.services.hls import next_mixed_slot, _normalize_source, _source_problem


def src(programs=2, filler=3, audio=2):
    return _normalize_source({"mode": "mixed", "video": [f"p{i}" for i in range(programs)],
                              "filler": [f"f{i}" for i in range(filler)],
                              "audio": [f"a{i}" for i in range(audio)], "filler_seconds": 60})


def run(s, steps):
    phase, idx, out = None, 0, []
    for _ in range(steps):
        phase, idx = next_mixed_slot(s, phase, idx)
        out.append(f"P{idx}" if phase == "program" else "F")
    return out


def test_alternates_program_and_filler():
    assert run(src(), 6) == ["P0", "F", "P1", "F", "P0", "F"]


def test_no_filler_plays_programs_back_to_back():
    assert run(src(filler=0), 3) == ["P0", "P1", "P0"]
    assert run(src(audio=0), 3) == ["P0", "P1", "P0"]


def test_no_programs_plays_filler_only():
    assert run(src(programs=0), 3) == ["F", "F", "F"]


def test_problems():
    assert _source_problem(src()) is None
    assert _source_problem(src(programs=0, filler=0)) is not None
    assert _source_problem(src(programs=0)) is None
    assert _source_problem(_normalize_source(["x"])) is None
