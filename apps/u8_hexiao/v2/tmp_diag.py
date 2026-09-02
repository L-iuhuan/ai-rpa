import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from core.audit import AuditSink

with tempfile.TemporaryDirectory() as tmp:
    runs_dir = os.path.join(tmp, "runs")
    os.makedirs(runs_dir)
    os.chmod(runs_dir, 0o555)
    sink = AuditSink(base_dir=tmp)
    try:
        sink.start()
        print("start completed, _started =", sink._started)
        print("_run_dir exists:", os.path.exists(sink._run_dir) if sink._run_dir else None)
        print("_steps_path exists:", os.path.exists(sink._steps_path) if sink._steps_path else None)
    except Exception as e:
        print("start raised exception:", e)
    finally:
        os.chmod(runs_dir, 0o755)
