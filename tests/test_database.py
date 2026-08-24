from db import database


def test_consume_first_launch_is_only_true_once(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()

    assert database.consume_first_launch() is True
    assert database.consume_first_launch() is False
