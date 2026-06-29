from horse_racing.cli import main
from horse_racing.data import load_horses_csv, sample_race, write_sample_csv


def test_sample_race_nonempty():
    horses = sample_race()
    assert len(horses) >= 2
    assert all(h.name for h in horses)


def test_write_and_load_roundtrip(tmp_path):
    path = write_sample_csv(tmp_path / "race.csv")
    horses = load_horses_csv(path)
    assert len(horses) == len(sample_race())
    assert horses[0].name == sample_race()[0].name


def test_load_requires_name_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("speed,odds\n100,3\n", encoding="utf-8")
    try:
        load_horses_csv(bad)
        assert False, "should have raised"
    except ValueError:
        pass


def test_load_partial_columns_uses_defaults(tmp_path):
    p = tmp_path / "partial.csv"
    p.write_text("name,speed\nアルファ,100\nベータ,90\n", encoding="utf-8")
    horses = load_horses_csv(p)
    assert horses[0].name == "アルファ"
    assert horses[0].speed == 100
    # 既定値が入る
    assert horses[0].odds == 10.0


def test_cli_sample_runs(capsys):
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "本命" in out


def test_cli_missing_file_errors(capsys):
    rc = main(["does_not_exist.csv"])
    assert rc == 1


def test_cli_write_sample(tmp_path, capsys):
    target = tmp_path / "out.csv"
    rc = main(["--write-sample", str(target)])
    assert rc == 0
    assert target.exists()
