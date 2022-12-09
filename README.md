`parrot-rcc` mimics https://pypi.org/project/carrot-rcc/ for Zeebe.

`parrot-rcc` is Work in progress.

```
Usage: parrot-rcc [OPTIONS] [ROBOTS]...

  Zeebe external task Robot Framework RCC client

  ROBOTS are RCC compatible automation code packages, which are most often
  created with `rcc robot wrap [-z robot.zip]`. They can also be passed as a
  space separated env RCC_ROBOTS

Options:
  --rcc-executable TEXT
  --rcc-controller TEXT
  --rcc-fixed-spaces              Allows RCC to execute multiple tasks
                                  concurrently in the same dependency
                                  environment.
  --rcc-s3-url TEXT               Base URL of the S3 compatible service used
                                  to store execution artifacts and work item
                                  files.
  --rcc-s3-access-key-id TEXT
  --rcc-s3-secret-access-key TEXT
  --rcc-s3-region TEXT
  --rcc-s3-bucket-logs TEXT
  --rcc-s3-bucket-data TEXT
  --rcc-s3-url-expires-in INTEGER
                                  Amount of seconds after generated presigned
                                  URLs to download S3 stored files without
                                  further authorization expire.
  --rcc-telemetry
  --task-timeout-ms INTEGER
  --task-max-jobs INTEGER
  --zeebe-hostname TEXT
  --zeebe-port INTEGER
  --camunda-client-id TEXT
  --camunda-client-secret TEXT
  --camunda-cluster-id TEXT
  --camunda-region TEXT
  --log-level TEXT
  --debug
  --help                          Show this message and exit.
```
