# task-runtime

Small collection of dependency-free Python helpers shared by containerized
tasks. It provides environment parsing, safe host/container path translation,
output-directory handling, progress records, stable task errors, subprocess
execution, and a few PostGIS SQL helpers.

The source is consumed directly from Git during a Docker build. It is not
published as a Python package.

## Requirements

- Python 3.9 or newer
- Standard library only

## Container contract

- `TASK_RUN_ID` is required and identifies one execution.
- `/out/<TASK_RUN_ID>/` is the default output directory.
- `/data` is the default host prefix and `/host-data` its container mount.
- Progress is written as `NN% message` on stdout.
- Structured messages are one-line JSON objects rooted at `task_runtime`.

Example:

```python
from task_runtime_base import PathTranslator, env, log_step, setup_out_dir
from task_runtime_base.progress import run_task


def main() -> None:
    source = PathTranslator.from_env().to_container_existing(env("INPUT"))
    output_dir = setup_out_dir()
    log_step(100, "Completed")


if __name__ == "__main__":
    run_task(main)
```

## Docker build context

A consuming Dockerfile can copy the source from a named context:

```dockerfile
COPY --from=task_runtime src/task_runtime_base /opt/task_runtime/task_runtime_base
ENV PYTHONPATH=/opt/task_runtime
```

Use a sibling checkout while developing:

```bash
docker buildx build --build-context task_runtime=../task_runtime .
```

For reproducible builds, use a Git tag and commit checksum as the named context.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

## License

MIT. See [LICENSE](LICENSE).

## Author

[Francisco Rafael Moreno Santana](https://github.com/Fran-4c4)
