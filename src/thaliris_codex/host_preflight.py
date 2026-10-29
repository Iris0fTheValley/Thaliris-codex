"""Pinned platform preflight, independent of the installed Python runtime.

No changed runtime code is invoked for diagnosis or recovery admission. The
Host's structured hook payload, not process ancestry or environment, supplies
the actor. No ambiguous actor can gain dangerous control authority from this preflight.
Offline operator administration is a distinct disconnected source route.
"""
from __future__ import annotations

import base64
import hashlib
import gzip
import io
import os
from pathlib import Path
import subprocess
import zlib

from .runtime_identity import WINDOWS_LAUNCHER_BINDING

NAME = "thaliris-preflight.ps1"


def degraded_source() -> str:
    """Small inline policy also survives a damaged preflight/trampoline."""
    source = r'''
function Present($path) {
  try { $null=[IO.File]::GetAttributes($path); return $true }
  catch [IO.FileNotFoundException] { return $false }
  catch [IO.DirectoryNotFoundException] { return $false }
}
function Unlinked($path) {
  while ($path) {
    if ((Present $path) -and (([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'linked observation path' }
    $path=[IO.Path]::GetDirectoryName($path)
  }
}
function IdentityHash($value) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$value))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
}
function Fenced($h) {
  try {
    if ($h.fenced -eq $true) { return $true }
    $path=if ($h.cwd) {[IO.Path]::GetFullPath([string]$h.cwd)} else {[Environment]::CurrentDirectory}
    while ($path -and -not (Present (Join-Path $path '.git'))) { $path=[IO.Path]::GetDirectoryName($path) }
    if (-not $path) { return $false }
    Unlinked (Join-Path $path '.git')
    # State existence and another task's fences grant no authority and do not
    # block ordinary delegation. Read deny-only exact session fence evidence.
    $hash=if ($h.session_id) {IdentityHash $h.session_id} else {''}
    $agent=if ($h.agent_id) {IdentityHash $h.agent_id} else {''}
    $p=Join-Path $path '.context/audit'; Unlinked $p
    if (Present $p) {
      foreach ($f in (Get-ChildItem -LiteralPath $p -Include 'session-fence.json','abandoned-child-fence.json' -Recurse -File -Force)) {
        try { Unlinked $f.FullName; $v=[IO.File]::ReadAllText($f.FullName)|ConvertFrom-Json } catch { continue }
        if ($f.Name -eq 'session-fence.json' -and $hash -and $v.session_id_hashes -ccontains $hash) { return $true }
        if ($agent -and ($v.agent_id_hashes -ccontains $agent -or $v.children.agent_id_hash -ccontains $agent)) { return $true }
      }
    }
    return $false
  } catch { return $false }
}
function FreshUnmanaged($h) {
  if ($h.readonly -eq $true -or $null -ne $h.agent_id -or $null -ne $h.agent_type) { return $false }
  $i=$h.tool_input
  $managed=([string]$i.agent_type -cmatch '^thaliris-' -or [string]$i.agentType -cmatch '^thaliris-')
  return -not $managed -or ($i.agent_type -cmatch '^thaliris-(investigator|curator|implementer|focused-implementer|reasoning-specialist|reviewer|verifier)$' -and ($null -eq $i.agentType -or $i.agentType -ceq $i.agent_type) -and (($i.fork_turns -ceq 'none' -and ($null -eq $i.fork_context -or $i.fork_context -eq $false)) -or ($null -eq $i.fork_turns -and $i.fork_context -eq $false)))
}
function ManagedTarget($h) {
  try {
    $target=$h.tool_input.target; if (-not $target) { $target=$h.tool_input.id }
    if (-not $target) { return $false }
    $path=if ($h.cwd) {[IO.Path]::GetFullPath([string]$h.cwd)} else {[Environment]::CurrentDirectory}
    while ($path -and -not (Present (Join-Path $path '.git'))) { $path=[IO.Path]::GetDirectoryName($path) }
    if (-not $path) { return $false }
    $p=Join-Path $path '.context/audit/lifecycle'; Unlinked $p
    if (-not (Present $p)) { return $false }
    if (-not $h.session_id) { return $false }
    $hash=IdentityHash $target; $session=IdentityHash $h.session_id
    $association=Join-Path $path ('.context/audit/session-tasks/'+$session+'.json'); Unlinked $association
    $a=[IO.File]::ReadAllText($association)|ConvertFrom-Json
    if ($a.version -ne 1 -or ([Guid]$a.task_id).ToString() -cne $a.task_id) { return $false }
    $key=(IdentityHash $a.task_id).Substring(0,24)
    $f=Join-Path $p ($key+'.json'); Unlinked $f
    $v=[IO.File]::ReadAllText($f)|ConvertFrom-Json
    if ($v.task_id -cne $a.task_id) { return $false }
    foreach ($child in $v.children) { if ($child.managed -eq $true -and ($child.task_name_hash -ceq $hash -or ($null -eq $child.task_name_hash -and $child.agent_id_hash -ceq $hash))) { return $true } }
    if ($v.pending_authorized_spawn.task_name_hash -ceq $hash -or $v.pending_authorized_spawn.native_agent_id_hash -ceq $hash) { return $true }
  } catch {}
  return $false
}
function Degraded($detail,$code='THALIRIS_RUNTIME_DRIFT') {
  if ($env:THALIRIS_HOOK_EVENT -cne 'PreToolUse') { return }
  try { $h=[Console]::In.ReadToEnd()|ConvertFrom-Json } catch { $h=$null }
  $tool=[string]$h.tool_name; if (-not $tool) { $tool=[string]$h.tool }
  $inputJson=$h.tool_input|ConvertTo-Json -Depth 32 -Compress
  $command=[string]$h.tool_input.command; if (-not $command) { $command=[string]$h.tool_input.cmd }
  $control=$command -match '(?i)(?:^|[;&|])\s*&?\s*["'']?(?:[^\s"'';|&]*[\\/])?(?:python[0-9.]*(\.exe)?|py(\.exe)?)["'']?\s+(-[IB]\s+)*(["'']?[^\r\n]*thaliris_offline_recovery\.py\b|-m\s+thaliris\.offline_recovery\b)'
  if ($tool -match '(?i)(spawn_agent|Agent)$') {
    $control=$true
    if ($tool -match '(?i)(?:^|[._:/])spawn_agent$' -and (FreshUnmanaged $h)) { $control=$false }
  }
  if ($tool -match '(?i)(followup_task|send_input|send_message|interrupt_agent|close_agent)$' -and ((ManagedTarget $h) -or $h.readonly -eq $true -or [string]$h.agent_type -cmatch '^thaliris-')) { $control=$true }
  $write=$tool -match '(?i)(apply_patch|file_change|write|edit|delete|move|rename)$'
  if ($tool -match '(?i)(Bash|exec_command|exec)$' -and $command -match '(?i)(Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|New-Item|apply_patch|git\s+(apply|commit|reset|restore|checkout|rebase)|[>])') { $write=$true }
  if ($write -and $inputJson -match '(?i)(\.context[\\/]+(state\.json|config\.json|tasks|audit[\\/]+(lifecycle|abandoned|external-recovery))|\.thaliris[\\/]+task-authority|\.codex[\\/]+(config\.toml|hooks\.json|thaliris\.json))') { $control=$true }
  if ($write -and $env:CODEX_HOME) {
    $homeRoot=[IO.Path]::GetFullPath($env:CODEX_HOME).Replace('\','/').TrimEnd([char]'/')
    $normalizedInput=$inputJson -replace '\\+','/'
    if ($normalizedInput -match ('(?i)'+[regex]::Escape($homeRoot)+'/(?:agents|thaliris-host-generations)/')) { $control=$true }
  }
  if ($command -match '(?i)^\s*&?\s*["'']?(thaliris(\.exe|\.cmd)?)["'']?\s' -and $command -match '(?i)\b(task-start|task-abandon|task-recover-state|task-recover-external|task-update|task-close|task-promote|task-artifact)\b') { $control=$true }
  if ($command -and $env:THALIRIS_EXECUTABLE -and $command -match ('^\s*&?\s*["'']?'+[regex]::Escape($env:THALIRIS_EXECUTABLE)+'["'']?\s')) { $control=$true }
  # A pending generation never exempts maintenance through another executor.
  if ($command -match '(?i)(?:^|[;&|])\s*&?\s*["'']?[^\r\n;|&]*?\s+codex-(install|uninstall)\b') { $control=$true }
  if ((Fenced $h) -or ($write -and ($h.readonly -eq $true -or [string]$h.agent_type -match '^thaliris-(reviewer|verifier)(-|$)'))) { $control=$true }
  $o=@{hookEventName='PreToolUse';additionalContext=($code+': '+$detail+'; assurance UNKNOWN.')}
  if ($control) { $o.permissionDecision='deny';$o.permissionDecisionReason='THALIRIS_CONTROL_AUTHORITY_UNAVAILABLE: '+$detail }
  @{hookSpecificOutput=$o}|ConvertTo-Json -Depth 32 -Compress|Write-Output
}
'''
    for old, new in (("$inputJson", "$j"), ("$command", "$c"), ("$control", "$d"), ("$detail", "$e"), ("$path", "$x"), ("FreshUnmanaged", "Fresh"), ("Present", "Exists"), ("Unlinked", "Safe"), ("ManagedTarget", "Target"), ("Fenced", "Fence"), ("IdentityHash", "Hash"), ("$association", "$q"), ("$session", "$s"), ("$target", "$t"), ("$managed", "$m"), ("$agent", "$g"), ("$hash", "$b")):
        source = source.replace(old, new)
    return "\n".join(line.strip() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def _platform_source() -> str:
    return (r'''$ErrorActionPreference='Stop'
function HashBytes($bytes) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
function FileHash($path) { return HashBytes ([IO.File]::ReadAllBytes($path)) }
function SafePath($path) {
  $item=Get-Item -LiteralPath $path -Force
  while ($null -ne $item) {
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('linked path: '+$path) }
    if ($item -is [IO.FileInfo]) { $item=$item.Directory } else { $item=$item.Parent }
  }
}
''' + degraded_source() + r'''
function AssertRuntime($bytes,$exe,$identity) {
  if ($identity -cnotmatch '^[0-9a-f]{64}$' -or (HashBytes $bytes) -cne $identity) { throw 'runtime manifest identity mismatch' }
  $m=[Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json
  if ($m.format -cne 'thaliris-installed-runtime-v1' -or $m.executable -cne $exe) { throw 'manifest topology mismatch' }
  SafePath $exe; SafePath $m.venv_dir; SafePath $m.package_dir
  $venv=(Get-Item -LiteralPath $m.venv_dir).FullName
  if (-not $exe.StartsWith($venv+'\',[StringComparison]::OrdinalIgnoreCase) -or -not $m.package_dir.StartsWith($venv+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'runtime topology outside pinned venv' }
  $expected=@{}; foreach ($e in $m.files.PSObject.Properties) {
    if ($e.Name -match '(^|/)\.\.?(/|$)|\\|^/|:' -or $e.Value -cnotmatch '^[0-9a-f]{64}$') { throw 'invalid manifest entry' }
    $expected[$e.Name]=$e.Value
  }
  if (-not $expected.ContainsKey('pyvenv.cfg')) { throw 'missing venv configuration pin' }
  $seen=@{}; $diff=[Collections.Generic.List[object]]::new()
  foreach ($item in (Get-ChildItem -LiteralPath $venv -Recurse -Force)) {
    SafePath $item.FullName
    if ($item.PSIsContainer) { continue }
    $relative=$item.FullName.Substring($venv.Length).TrimStart('\').Replace('\','/')
    $actual=FileHash $item.FullName; $wanted=$expected[$relative]
    if (-not $wanted) { $wanted='ABSENT' }
    if ($actual -cne $wanted) { $diff.Add(@{path=$relative;expected=$wanted;actual=$actual;surface=$(if($relative.EndsWith('.pyc')){'python_bytecode'}else{'runtime'})}) }
    $seen[$relative]=$true
  }
  foreach ($name in $expected.Keys) { if (-not $seen.ContainsKey($name)) { $diff.Add(@{path=$name;expected=$expected[$name];actual='ABSENT';surface='runtime'}) } }
  if ($diff.Count) { throw ($diff|ConvertTo-Json -Depth 8 -Compress) }
  if ((FileHash $exe) -cne $m.executable_sha256) { throw 'launcher manifest hash mismatch' }
  $location=Join-Path $venv 'thaliris-runtime-location.json'
  if (Test-Path -LiteralPath $location) {
    SafePath $location
    if (-not $expected.ContainsKey('thaliris-runtime-location.json')) { throw 'runtime location anchor is not pinned' }
    $anchor=Get-Content -LiteralPath $location -Raw -Encoding UTF8|ConvertFrom-Json
    $interpreter=Join-Path ([IO.Path]::GetDirectoryName($exe)) 'python.exe'
    $keys=@($anchor.PSObject.Properties.Name|Sort-Object)
    if (($keys -join ',') -cne 'executable,format,interpreter,venv_dir' -or $anchor.format -cne 'thaliris-runtime-location-v1' -or $anchor.venv_dir -ine $venv -or $anchor.executable -ine $exe -or $anchor.interpreter -ine $interpreter) { throw 'runtime location changed: installed venv may not be relocated' }
  }
  if ([IO.Path]::GetExtension($exe) -ieq '.exe') {
    # Use the same short/long distlib ABI as Python installation admission.
    # Successful dispatch via a surviving old interpreter is still relocation.
    $data=[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($exe))
    $bindings=[regex]::Matches($data,'__WINDOWS_LAUNCHER_BINDING__PK\x03\x04')
    if ($bindings.Count -ne 1) { throw 'Windows console launcher interpreter binding unavailable' }
    $bound=$bindings[0].Groups[1].Value;if (-not $bound) { $bound=$bindings[0].Groups[2].Value }
    $interpreter=Join-Path ([IO.Path]::GetDirectoryName($exe)) 'python.exe'
    if (-not [IO.Path]::IsPathRooted($bound) -or $bound -ine $interpreter) { throw 'runtime launcher location changed: interpreter must be in same final directory' }
    SafePath $interpreter
  }
  $config=Get-Content -LiteralPath (Join-Path $venv 'pyvenv.cfg') -Raw
  if ($config -notmatch '(?im)^\s*include-system-site-packages\s*=\s*false\s*$') { throw 'system site packages enabled' }
  foreach ($pth in (Get-ChildItem -LiteralPath $venv -Recurse -Force -Filter '*.pth' -File)) {
    foreach ($line in (Get-Content -LiteralPath $pth.FullName)) { if ($line.Trim() -and -not $line.TrimStart().StartsWith('#')) { throw 'external .pth execution or import path' } }
  }
}
function Replay($hostHome,$journal,$raw) {
  $h=$raw|ConvertFrom-Json
  if ($null -eq $h -or $null -ne $h.agent_id -or $null -ne $h.agent_type -or $h.readonly -eq $true -or $h.fenced -eq $true) { throw 'HOST_MAINTENANCE_ACTOR_DENIED' }
  $tool=[string]$h.tool_name; if (-not $tool) { $tool=[string]$h.tool }
  if ($tool -notmatch '(?i)(?:^|[._:/])(Bash|exec_command|exec)$') { throw 'not a direct maintenance command' }
  $command=[string]$h.tool_input.cmd; if (-not $command) { $command=[string]$h.tool_input.command }
  # Parse literals, never evaluate the submitted command or expand variables.
  $tokens=$null;$errors=$null
  $ast=[Management.Automation.Language.Parser]::ParseInput($command,[ref]$tokens,[ref]$errors)
  if ($errors.Count -or $ast.EndBlock.Statements.Count -ne 1) { throw 'compound maintenance command' }
  $pipeline=$ast.EndBlock.Statements[0]
  if ($pipeline -isnot [Management.Automation.Language.PipelineAst] -or $pipeline.PipelineElements.Count -ne 1) { throw 'compound maintenance command' }
  $call=$pipeline.PipelineElements[0]
  if ($call -isnot [Management.Automation.Language.CommandAst] -or $call.Redirections.Count -or $call.InvocationOperator -notin @('Unknown','Ampersand')) { throw 'indirect maintenance command' }
  $arguments=@();foreach ($element in $call.CommandElements) {
    if ($element -is [Management.Automation.Language.StringConstantExpressionAst]) { $arguments+= [string]$element.Value }
    elseif ($element -is [Management.Automation.Language.CommandParameterAst] -and $null -eq $element.Argument) { $arguments+= '--'+$element.ParameterName.TrimStart('-') }
    else { throw 'nonliteral maintenance argument' }
  }
  if ($arguments.Count -lt 4 -or $arguments[1] -cnotin @('codex-install','codex-uninstall')) { throw 'not direct maintenance' }
  $options=@{};for($i=2;$i -lt $arguments.Count;$i+=2) {
    if ($i+1 -ge $arguments.Count -or $arguments[$i] -cnotin @('--maintenance-contract','--executable','--sha256','--execution-constraint') -or $options.ContainsKey($arguments[$i])) { throw 'invalid maintenance options' }
    $options[$arguments[$i]]=$arguments[$i+1]
  }
  $filename=$options['--maintenance-contract'];if (-not $filename -or -not [IO.Path]::IsPathRooted($filename)) { throw 'missing absolute maintenance contract' }
  SafePath $filename;SafePath $journal
  $record=Get-Content -LiteralPath $journal -Raw -Encoding UTF8|ConvertFrom-Json
  $contractBytes=[IO.File]::ReadAllBytes($filename);$intent=[Text.Encoding]::UTF8.GetString($contractBytes)|ConvertFrom-Json
  if ($record.format -cne 'thaliris-host-transition-v1' -or $record.phase -cnotin @('PREPARED','COMMITTED') -or $record.operation -cne $arguments[1] -or $record.contract_sha256 -cne (HashBytes $contractBytes) -or $intent.format -cne 'thaliris-host-maintenance-v1' -or $intent.operation -cne $arguments[1] -or $intent.codex_home -ine $hostHome -or -not ([string]$intent.human_instruction).Trim()) { throw 'original maintenance intent unavailable' }
  $exe=[string]$intent.executor.executable
  if ($arguments[0] -cne $exe) { throw 'not the original maintenance executor' }
  $encoded=$record.executor_runtime
  if (-not $encoded) {
    # Earlier journals can prove the executor only through an exact snapshot.
    foreach ($value in @($record.before.'thaliris-install.json',$record.after.'thaliris-install.json')) {
      if ($value -and (HashBytes ([Convert]::FromBase64String($value))) -ceq $intent.executor.runtime_sha256) { $encoded=$value;break }
    }
  }
  if (-not $encoded) { throw 'original executor snapshot unavailable' }
  AssertRuntime ([Convert]::FromBase64String($encoded)) $exe $intent.executor.runtime_sha256
  # Only now may the selected immutable runtime interpret its native schemas.
  # It reads the original payload and validates provenance, receipts and fences.
  $env:CODEX_HOME=$hostHome;$env:PYTHONPATH='';$env:PYTHONHOME='';$env:PYTHONNOUSERSITE='1';$env:PYTHONDONTWRITEBYTECODE='1'
  $OutputEncoding=[Text.UTF8Encoding]::new($false)
  $output=$raw | & $exe audit-hook PreToolUse --maintenance-replay-contract $filename
  if ($LASTEXITCODE -ne 0) { throw 'verified executor cannot check native replay' }
  $decision=($output|Out-String)|ConvertFrom-Json
  if ($decision.hookSpecificOutput.hookEventName -cne 'PreToolUse' -or $decision.hookSpecificOutput.permissionDecision -cnotin @('allow','deny')) { throw 'invalid replay decision' }
  $output|Write-Output
}
''').replace('__WINDOWS_LAUNCHER_BINDING__', WINDOWS_LAUNCHER_BINDING)


def _stale_source() -> str:
    return r'''
# Failure path only: the Host still holds a pin ($pin over file $name) from a
# previously committed generation, and the current files are a verified
# committed generation. This changes the diagnosis only, never the decision.
$stale='Codex still runs hook arguments of an earlier committed Thaliris install generation; the installed generation is current and verified. Restart Codex (app-server) once; Task, Authority, Controller associations and delegated mode are kept, so do not switch execution mode. No hot reload'
function StaleHost($manifest,$name,$pin) {
  try {
    $bytes=[IO.File]::ReadAllBytes($manifest);$now=HashBytes $bytes
    $gh=[IO.Path]::GetDirectoryName($manifest)
    $disk=if ($name -ceq 'thaliris-install.json') {$now} else {FileHash (Join-Path $gh $name)}
    if ($pin -cnotmatch '^[0-9a-f]{64}$' -or $disk -ceq $pin) { return $false }
    $old=$false;$new=$false
    foreach ($f in (Get-ChildItem -LiteralPath (Join-Path $gh 'thaliris-host-generations') -Filter '*.json' -File -Force)) {
      SafePath $f.FullName;$r=[IO.File]::ReadAllText($f.FullName)|ConvertFrom-Json
      if ($r.phase -cne 'COMMITTED') { continue }
      foreach ($v in @($r.before.$name,$r.after.$name)) { if ($v -and (HashBytes ([Convert]::FromBase64String($v))) -ceq $pin) { $old=$true } }
      $v=$r.after.'thaliris-install.json'
      if ($v -and (HashBytes ([Convert]::FromBase64String($v))) -ceq $now) {
        $ok=$true
        foreach ($n in 'thaliris-hook.cmd','thaliris-preflight.ps1') { $w=$r.after.$n; if ($w -and (HashBytes ([Convert]::FromBase64String($w))) -cne (FileHash (Join-Path $gh $n))) { $ok=$false } }
        if ($ok) { $new=$true }
      }
    }
    if (-not ($old -and $new)) { return $false }
    AssertRuntime $bytes (([Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json).executable) $now
    return $true
  } catch { return $false }
}
'''


def script_bytes() -> bytes:
    return (_platform_source() + _stale_source() + r'''
try {
  $manifest=$env:THALIRIS_INSTALL_MANIFEST; $identity=$env:THALIRIS_RUNTIME_SHA256; $exe=$env:THALIRIS_EXECUTABLE
  $hostHome=[IO.Path]::GetDirectoryName($manifest);$journal=Join-Path $hostHome 'thaliris-host-transition.json'
  if (Exists $journal) {
    if ($env:THALIRIS_HOOK_EVENT -ceq 'PreToolUse') {
      $raw=[Console]::In.ReadToEnd()
      Replay $hostHome $journal $raw
      # The replay decision consumes the payload; skip ordinary Python dispatch.
      exit 1
    }
    throw 'HOST_TRANSITION_PENDING: replay the original standalone maintenance contract'
  }
  SafePath $manifest
  AssertRuntime ([IO.File]::ReadAllBytes($manifest)) $exe $identity
  if ($env:THALIRIS_HOOK_EVENT -ceq 'SessionStart') {
    # The verified installed package, never a project checkout, owns this
    # narrow restoration policy. Read once and forward the exact native bytes
    # to the original audit-hook pipeline after the actor-preserving check.
    $python=Join-Path ([IO.Path]::GetDirectoryName($exe)) 'python.exe'
    & $python -I -B -m thaliris_codex.catalog_recovery --home $hostHome --runtime-sha256 $identity --session-start --managed-hook-abi $env:THALIRIS_SESSION_START_ABI
    # The receiver distinguishes auxiliary recovery diagnostics from startup
    # rejection and preserves the native Hook result. Do not normalize it.
    exit $LASTEXITCODE
  }
  exit 0
} catch {
  $detail=$_.Exception.Message;$code='THALIRIS_RUNTIME_DRIFT'
  if ($detail -ceq 'runtime manifest identity mismatch' -and (StaleHost $manifest 'thaliris-install.json' $identity)) { $code='THALIRIS_RUNTIME_STALE_HOST_LOAD';$detail=$stale }
  if ($env:THALIRIS_HOOK_EVENT -ceq 'PreToolUse') {
    if ($null -eq $raw) { $raw=[Console]::In.ReadToEnd() }
    # Degraded reads Console.In; supply the already consumed payload directly.
    $reader=[IO.StringReader]::new($raw); [Console]::SetIn($reader)
    Degraded $detail $code
  } else {
    if ($code -cne 'THALIRIS_RUNTIME_DRIFT') { $detail=$code+': '+$detail }
    if ($env:THALIRIS_HOOK_EVENT -ceq 'SessionStart') {
      [Console]::Error.WriteLine('THALIRIS_CATALOG_RECOVERY_UNKNOWN: '+$detail)
    }
  }
  if (-not $env:THALIRIS_HOOK_EVENT) {
    @{ok=$false;status='THALIRIS_RUNTIME_IDENTITY_MISMATCH';execution_assurance='UNKNOWN';diagnostic=$detail;decision_required=$true}|ConvertTo-Json -Depth 32 -Compress|Write-Output
  }
  exit 1
}
''').encode("utf-8")


def verify_runtime(executable: Path, contents: bytes) -> None:
    """Exercise the actual platform guard before admitting a new generation.

    This independent PowerShell entry imports no installed Python and needs no
    working Host hook, runner, or project task. Inputs are data, never code.
    """
    if os.name != "nt":
        return
    from .runtime_identity import child_environment, manifest_identity
    environment = child_environment()
    environment.update(THALIRIS_PROBE_MANIFEST=base64.b64encode(contents).decode("ascii"),
                       THALIRIS_PROBE_EXE=str(executable),
                       THALIRIS_PROBE_IDENTITY=manifest_identity(contents))
    source = _platform_source() + r'''
try {
  AssertRuntime ([Convert]::FromBase64String($env:THALIRIS_PROBE_MANIFEST)) $env:THALIRIS_PROBE_EXE $env:THALIRIS_PROBE_IDENTITY
  exit 0
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
'''
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                             packed_literal_without_variables(source)],
                            env=environment, capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError("independent platform runtime preflight failed: "
                         + result.stderr.decode("utf-8", errors="replace").strip())


def recovery_source(previous: bool = False, pin: bool = False) -> str:
    """Literal recovery policy survives removed uninstall entrypoints.

    This uses the same runtime verifier and replay parser as the on-disk
    preflight. It imports no damaged/new disk policy to decide admission.
    The caller sets $cause; with ``pin`` also $expected, its Hook script pin. ``previous`` renders the exact 0.5.4 literal for recognition.
    """
    if previous:
        return _strip(_platform_source() + r'''
try {
  $hostHome=[IO.Path]::GetDirectoryName($env:THALIRIS_INSTALL_MANIFEST)
  $journal=Join-Path $hostHome 'thaliris-host-transition.json'
  if ($env:THALIRIS_HOOK_EVENT -cne 'PreToolUse' -or -not (Exists $journal)) { throw 'platform preflight unavailable' }
  $raw=[Console]::In.ReadToEnd()
  Replay $hostHome $journal $raw
} catch {
  if ($null -ne $raw) { [Console]::SetIn([IO.StringReader]::new($raw)) }
  Degraded $_.Exception.Message
}
''')
    stale = r'''
# The Host pins $expected for thaliris-hook.cmd. A committed upgrade
# replaced it and the current committed install verifies: only an unrestarted
# Host remains. Compact twin of StaleHost to fit the Hook command line.
function Stale($m,$n,$w) {
  try {
    $o=$false;$c=$false;$k=FileHash $m;$gh=[IO.Path]::GetDirectoryName($m);$d=FileHash (Join-Path $gh $n)
    # The Host never ran this preflight; a damaged one would survive a restart.
    $y=FileHash (Join-Path $gh 'thaliris-preflight.ps1')
    if ($w -cnotmatch '^[0-9a-f]{64}$' -or $d -ceq $w) { return $false }
    foreach ($f in (Get-ChildItem -LiteralPath (Join-Path $gh 'thaliris-host-generations') -Filter '*.json' -File -Force)) {
      SafePath $f.FullName;$r=[IO.File]::ReadAllText($f.FullName)|ConvertFrom-Json
      if ($r.phase -cne 'COMMITTED') { continue }
      foreach ($v in @($r.before.$n,$r.after.$n)) { if ($v -and (HashBytes ([Convert]::FromBase64String($v))) -ceq $w) { $o=1 } }
      $v=$r.after.'thaliris-install.json';$u=$r.after.$n;$z=$r.after.'thaliris-preflight.ps1'
      if ($v -and $u -and $z -and (HashBytes ([Convert]::FromBase64String($v))) -ceq $k -and (HashBytes ([Convert]::FromBase64String($u))) -ceq $d -and (HashBytes ([Convert]::FromBase64String($z))) -ceq $y) { $c=1 }
    }
    if (-not ($o -and $c)) { return $false }
    $b=[IO.File]::ReadAllBytes($m);AssertRuntime $b (([Text.Encoding]::UTF8.GetString($b)|ConvertFrom-Json).executable) $k
    return $true
  } catch { return $false }
}
''' if pin else ""
    return _strip(_platform_source() + stale + r'''
try {
  $hostHome=[IO.Path]::GetDirectoryName($env:THALIRIS_INSTALL_MANIFEST)
  $journal=Join-Path $hostHome 'thaliris-host-transition.json'
  if ($env:THALIRIS_HOOK_EVENT -cne 'PreToolUse' -or -not (Exists $journal)) { throw 'platform preflight unavailable' }
  $raw=[Console]::In.ReadToEnd()
  Replay $hostHome $journal $raw
} catch {
  if ($null -ne $raw) { [Console]::SetIn([IO.StringReader]::new($raw)) }
  # Keep the concrete cause instead of a generic message.
  $e=$_.Exception.Message;$code='THALIRIS_RUNTIME_DRIFT';if ($cause) { $e=$e+' ('+$cause+')' }
''' + (r'''
  if (Stale $env:THALIRIS_INSTALL_MANIFEST 'thaliris-hook.cmd' $expected) { $code='THALIRIS_RUNTIME_STALE_HOST_LOAD';$e='Codex still runs hooks of an earlier committed Thaliris install; the current install verifies. Restart Codex once; Task, Authority, Controller and delegated mode are kept' }
''' if pin else "") + r'''
  Degraded $e $code
}
''')


def _strip(source: str) -> str:
    # Recovery is also packed inside the global Hook command. Keep canonical
    # on-disk comments, but leave cmd enough space for its shell wrapper.
    return "\n".join(line.strip() for line in source.splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))


# The on-disk preflight digest pinned by 0.5.4 and earlier entry literals.
_PREVIOUS_PREFLIGHT_SHA256 = "e8974be7983125d9c3d592df9e1121b07608623f87926302984f7c24b436c542"


def entry_source(previous: bool = False) -> str:
    if previous:
        return (
            "$ErrorActionPreference='Stop';try{"
            "$p=$env:THALIRIS_PREFLIGHT;"
            "$s=[Security.Cryptography.SHA256]::Create();"
            "try{$a=([BitConverter]::ToString($s.ComputeHash([IO.File]::ReadAllBytes($p)))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose()};"
            f"if($a -cne '{_PREVIOUS_PREFLIGHT_SHA256}'){{throw 'preflight hash mismatch'}};"
            "& $p;exit $LASTEXITCODE}catch{"
            + "if($env:THALIRIS_HOOK_EVENT){"
            + recovery_source(previous=True)
            + "}else{"
            + "@{ok=$false;status='THALIRIS_RUNTIME_IDENTITY_MISMATCH';execution_assurance='UNKNOWN';diagnostic=$_.Exception.Message}|ConvertTo-Json -Compress|Write-Output};exit 1}"
        )
    digest = hashlib.sha256(script_bytes()).hexdigest()
    # Run the hashed bytes themselves: `& file.ps1` is refused under the
    # default Restricted execution policy and would reread a mutable file.
    # The preflight digest is part of the Hook script the Host pins, so a
    # replaced preflight is diagnosed there (see recovery_source's pin).
    return (
        "$ErrorActionPreference='Stop';try{"
        "$b=[IO.File]::ReadAllBytes($env:THALIRIS_PREFLIGHT);"
        "$s=[Security.Cryptography.SHA256]::Create();"
        "try{$a=([BitConverter]::ToString($s.ComputeHash($b))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose()};"
        f"if($a -cne '{digest}'){{throw 'preflight hash mismatch'}};"
        "& ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString($b)));exit $LASTEXITCODE}catch{"
        + "$cause=$_.Exception.Message;if($env:THALIRIS_HOOK_EVENT){"
        + recovery_source()
        + "}else{"
        + "@{ok=$false;status='THALIRIS_RUNTIME_IDENTITY_MISMATCH';execution_assurance='UNKNOWN';diagnostic=$cause}|ConvertTo-Json -Compress|Write-Output};exit 1}"
    )


def command_entry(previous: bool = False) -> str:
    """Pack one literal policy to fit cmd's physical 8191-character line."""
    return packed_literal_without_variables(entry_source(previous))


def encoded_entry() -> str:
    """Compatibility encoding for callers needing PowerShell EncodedCommand."""
    return base64.b64encode(entry_source().encode("utf-16le")).decode("ascii")


def inline_degraded() -> str:
    """Pinned literal policy compressed to fit cmd's physical line limit.

    Only this generated literal is evaluated, never hook input or disk code.
    """
    return packed_literal(degraded_source())


_PACKED_PREFIX = "$r=[IO.StreamReader]::new([IO.Compression.GZipStream]::new([IO.MemoryStream]::new([Convert]::FromBase64String('"
_PACKED_SUFFIX = "')),[IO.Compression.CompressionMode]::Decompress));try{iex $r.ReadToEnd()}finally{$r.Dispose()};"
_VARIABLE_FREE_PACKED_PREFIX = "iex ([IO.StreamReader]::new([IO.Compression.GZipStream]::new([IO.MemoryStream]::new([Convert]::FromBase64String('"
_VARIABLE_FREE_PACKED_SUFFIX = "')),[IO.Compression.CompressionMode]::Decompress)).ReadToEnd())"


def packed_literal(source: str) -> str:
    """Encode only generated literal code, including the outer Host command."""
    data = base64.b64encode(gzip.compress(source.encode(), mtime=0)).decode()
    return _PACKED_PREFIX + data + _PACKED_SUFFIX


def packed_literal_without_variables(source: str) -> str:
    """Pack generated code behind a loader safe inside nested PowerShell quotes."""
    data = base64.b64encode(gzip.compress(source.encode(), mtime=0)).decode()
    return _VARIABLE_FREE_PACKED_PREFIX + data + _VARIABLE_FREE_PACKED_SUFFIX


def unpack_literal(source: str) -> str:
    """Decode for exact ownership comparison, never evaluation or authority."""
    if source.startswith(_PACKED_PREFIX):
        prefix, suffix = _PACKED_PREFIX, _PACKED_SUFFIX
    elif source.startswith(_VARIABLE_FREE_PACKED_PREFIX):
        prefix, suffix = _VARIABLE_FREE_PACKED_PREFIX, _VARIABLE_FREE_PACKED_SUFFIX
    else:
        return source
    if not source.endswith(suffix):
        raise ValueError("invalid packed Host literal")
    data = base64.b64decode(source[len(prefix):-len(suffix)], validate=True)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            raw = stream.read(65537)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError("invalid packed Host literal") from exc
    if len(raw) > 65536:
        raise ValueError("oversized packed Host literal")
    return raw.decode("utf-8")
