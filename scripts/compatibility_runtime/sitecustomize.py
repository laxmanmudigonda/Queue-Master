# Validation adapter only: PGlite's socket proxy has incomplete extended-protocol support.
import psycopg

_original_connect = psycopg.connect


def connect(*args, **kwargs):
    kwargs["cursor_factory"] = psycopg.ClientCursor
    kwargs["prepare_threshold"] = None
    return _original_connect(*args, **kwargs)


psycopg.connect = connect
