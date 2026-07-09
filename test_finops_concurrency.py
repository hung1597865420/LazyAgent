import os
import tempfile
import threading


def main():
    with tempfile.TemporaryDirectory() as workspace:
        os.environ["WORKSPACE_ROOT"] = workspace

        import agents

        agents.init_finops_db()
        run_id = "finops-concurrency-self-check"

        threads = [
            threading.Thread(
                target=agents.log_step_to_db,
                args=(run_id, "tester", "gpt-5.3-codex", 10, 5, 20, False),
            )
            for _ in range(32)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        agents.log_run_to_db(run_id, "self_check", 123)
        stats = agents.get_finops_stats()
        assert stats["total_steps"] == 32, stats
        assert stats["recent_runs"][0]["run_id"] == run_id, stats


if __name__ == "__main__":
    main()
