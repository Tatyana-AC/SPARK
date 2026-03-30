import traceback


def _write_text(path, text):
    with open(path, "w") as handle:
        handle.write(text)


def _append_line(path, line):
    with open(path, "a") as handle:
        handle.write(f"{line}\n")


def _best_effort_write(path, text):
    try:
        _write_text(path, text)
    except OSError:
        return


def _best_effort_append(path, line):
    try:
        _append_line(path, line)
    except OSError:
        return


def run_with_diagnostics(callback, *, error_log_path, trace_log_path):
    _best_effort_write(error_log_path, "")
    _best_effort_write(trace_log_path, "")

    def record_step(step):
        _best_effort_append(trace_log_path, step)

    try:
        return callback(record_step)
    except Exception as exc:
        try:
            with open(error_log_path, "w") as handle:
                handle.write("Unhandled exception in code.py\n")
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
        except OSError:
            pass
        raise
