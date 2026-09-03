---
name: andromeda-ssh
description: Connect to and safely inspect or administer the Andromeda Ubuntu Linux host over SSH from Windows PowerShell. Use for requests involving Andromeda, jeff@andromeda, remote shell commands, system status, services, logs, cron, systemd timers, packages, files, reboots, or other Linux operations on that host.
---

# Andromeda SSH

Treat Andromeda as a remote Ubuntu Linux host reached from Windows PowerShell.

## Connection facts

- SSH target: `jeff@andromeda`
- Remote environment: Ubuntu Linux; use Linux commands, paths, cron, and systemd.
- Local command environment: PowerShell. Account for PowerShell parsing before text reaches SSH.
- Sudo password environment variable: `ANDROMEDA_SUDO_PASSWORD` in the local Windows process environment.
- Discover dynamic state such as timezone, OS version, paths, and service status instead of assuming it remains unchanged.
- Never print, log, interpolate into command text, or include the value of `ANDROMEDA_SUDO_PASSWORD` in commentary or user-facing output.

## Workflow

1. For a read-only request, connect and inspect directly.
2. Before a state-changing command, resolve the exact remote target and inspect its current state when practical.
3. Use ordinary user privileges unless the operation requires root.
4. For root access, try non-interactive sudo first with `sudo -n`. If it fails, read the password from `$env:ANDROMEDA_SUDO_PASSWORD` and pipe it to remote `sudo -S -p ''`. If the variable is absent, tell the user to set it and restart Codex so the process inherits it; do not ask them to paste the password into chat.
5. After any change, verify the resulting file, service, schedule, permissions, or other relevant state.
6. Report the outcome and any time-sensitive context, especially the remote timezone for schedules.

## Command patterns

Check connectivity without prompting for an SSH password:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 jeff@andromeda 'hostname; uname -a'
```

Run a simple remote command. Prefer a single-quoted PowerShell argument so local PowerShell does not expand remote `$variables` or pipelines:

```powershell
ssh jeff@andromeda 'systemctl is-active cron; timedatectl show -p Timezone'
```

Run a simple privileged command when passwordless sudo is available:

```powershell
ssh jeff@andromeda 'sudo -n systemctl status cron --no-pager'
```

For complex commands, avoid fragile nested quoting by encoding a UTF-8 shell script locally:

```powershell
$remoteScript = @'
set -eu
hostname
systemctl is-active cron
'@
$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
ssh jeff@andromeda "echo '$payload' | base64 -d | bash"
```

For a complex privileged script, use the same pattern with non-interactive sudo:

```powershell
ssh jeff@andromeda "echo '$payload' | base64 -d | sudo -n bash"
```

If sudo requires a password, first ensure the environment variable exists without displaying its value:

```powershell
if (-not $env:ANDROMEDA_SUDO_PASSWORD) { throw 'ANDROMEDA_SUDO_PASSWORD is not available in this process.' }
```

Pipe it to sudo for a simple privileged command:

```powershell
$env:ANDROMEDA_SUDO_PASSWORD | ssh jeff@andromeda "sudo -S -p '' systemctl status cron --no-pager"
```

For a complex privileged script, reserve standard input for sudo authentication and embed only the non-secret base64 payload in the remote command:

```powershell
$env:ANDROMEDA_SUDO_PASSWORD | ssh jeff@andromeda "sudo -S -p '' sh -c 'echo $payload | base64 -d | bash'"
```

## Operational guidance

- Use `systemctl` and `journalctl` for services and logs.
- Inspect both cron and systemd timers for scheduling questions. Include `/etc/crontab`, `/etc/cron.d`, `/var/spool/cron/crontabs`, `systemctl list-timers --all`, and one-off `at` jobs when a comprehensive sweep is needed.
- Prefer `/etc/cron.d/<descriptive-name>` for explicit system-wide cron entries. Use a valid filename, end the file with a newline, set ownership to `root:root`, set mode `0644`, and verify that `cron` is active.
- Quote remote paths and variables carefully. Use the base64 script pattern when a command contains nested quotes, pipes, regex alternation, command substitutions, or multiple shell layers.
- Set reasonable SSH and command timeouts. A reboot can terminate the SSH connection before returning success; verify reachability again after allowing the host time to restart.
- Do not perform destructive or availability-impacting actions unless the user's request clearly authorizes them.
