# Developing TTMediaBot with an AI assistant

This guide is for contributors who fix bugs or add features with the help of an AI
coding assistant (Claude, ChatGPT, Gemini, Copilot and so on). The tool does not
matter; the way you brief it does.

The short version: **tell the AI what happened, in order, with evidence. Do not hand
it the whole bot and say "check everything".**

---

## 1. Why "please check the whole bot" does not work

A request such as *"check all the files of this bot and fix the bugs"* fails for
predictable reasons:

- The bot is about 11,000 lines of Python plus a Node.js bridge. The AI cannot hold it
  all in mind, so it skims, and it fills the gaps with guesses. Those guesses are what
  people call hallucinations: a function that does not exist, a config option nobody
  wrote, a "bug" that is really a design decision.
- With no symptom to chase, the AI "improves" whatever looks odd. You get a large diff
  that mixes real fixes, style changes and new behaviour, and nobody can review it.
- It cannot know what is *wrong* from the code alone. Most real bugs here only show up
  with a certain video, network or timing (for example a YouTube stream that answers
  `403` only on the first second). Without the log it has nothing to go on.

Give it the **chronology** instead: what you did, what you saw, when, and what the log
says. A small, specific question gets a small, checkable answer.

## 2. Before you ask: collect the facts

1. **Reproduce it** and write down the exact steps (the command you typed, in which
   order, and how many times).
2. **Copy the relevant log lines** from `TTMediaBot.log` with their timestamps, from a
   little before the problem to a little after. Ten to fifty lines are usually enough.
   Do not paste the whole file.
3. **Note the version**: `app_version` in `bot/app_vars.py`, your OS, your Python version.
4. **Remove secrets** from anything you paste: `config.json` passwords, the Gemini API
   key, YouTube cookie files, server addresses you do not want public. Never paste
   `cookies.txt`.

## 3. The prompt template

Copy this, fill in the blanks, and send it as the first message of a **new** session.

```text
I maintain TTMediaBot (a TeamTalk music bot, Python, version <x.y.z>). I need help with ONE bug.

ENVIRONMENT
- OS / Python: <Windows 11, Python 3.15 ...>
- Service involved: <yt / ytm / direct URL / AI ...>

WHAT I DID (in order)
1. <typed "p senja gurau" in the channel>
2. <...>

WHAT I EXPECTED
<the bot plays "Senja Gurau">

WHAT HAPPENED
<the chat said "Playing Bersenja Gurau" but a different song was heard>

EVIDENCE (log, with timestamps)
<paste 10-50 lines>

WHAT I ALREADY TRIED OR RULED OUT
<tried again after a minute: it worked>

RULES
- Do not change any behaviour that is not part of this bug. No new features.
- Do not rename or reformat code you do not need to touch.
- If you are not sure about something (an API, an option, a version), say "I am not
  sure" and tell me how to verify it. Do not invent.

STEP 1 (no code yet)
Explain what in the code can produce this evidence. Name the files and functions, and
say which part is proven by my log and which part is only your hypothesis.
```

Only after you agree with the explanation, continue with:

```text
STEP 2
Write a test that fails because of this bug (tests live in tests/, run them with
python -m unittest discover -s tests -t .). Show me the test first.

STEP 3
Now make the smallest change that makes the test pass. Show only the changed lines.
Then list every other test or behaviour that this change could affect.
```

## 4. A good brief against a bad one

**Bad**

> Please check this bot's files completely and fix all the bugs. Make it better.

**Good** (a real case from this repository)

> A friend typed `p senja gurau` on 13 Oct at 10:00. The bot wrote "Playing Bersenja
> Gurau", but he heard "Dunia Yang Nanti" and typed the command again a minute later.
> Log:
> ```
> 10:00:53,059 INFO    [PlaybackTiming] command_response_sent command=p response='Playing Bersenja Gurau - Raim laode - Topic'
> 10:00:53,192 WARNING [FFmpeg] Playback ended with an error ...: HTTP error 403 Forbidden
> 10:00:53,193 WARNING [PlaybackTiming] youtube_stream_refresh_started track='Bersenja Gurau - Raim laode - Topic'
> 10:00:53,679 WARNING [FFmpeg] Playback ended with an error ...: HTTP error 403 Forbidden
> 10:00:53,679 INFO    [PlaybackTiming] next_track_started previous_track='Bersenja Gurau - Raim laode - Topic'
> 10:00:53,796 INFO    [PlaybackTiming] track_url_started ... track='Dunia Yang Nanti - Raim Laode'
> ```
> Explain how the track after the second 403 can be a different song, in
> `bot/player/__init__.py` (`on_end_file`).

The good brief names the symptom, the time, the evidence and the place to look. The AI
can answer it exactly, and you can check the answer against the log.

## 5. A map of the code to give the AI

Point it at the smallest area that matches the symptom.

| Symptom | Look at |
| :--- | :--- |
| Wrong or skipped song, stream errors, retries | `bot/player/__init__.py` (`on_end_file`, `_retry_failed_stream`), `bot/player/track.py` |
| Audio stutters, stalls, crackling | `bot/player/ffmpeg_engine.py` (`_pump`, `_read_stderr`, `_write`) |
| Search returns the wrong item | `bot/services/yt.py`, `bot/services/ytm.py`, `bot/services/result_filter.py`, `youtube_bridge/server.mjs` |
| Autoplay / recommendations | `_fetch_autoplay_sync` in `yt.py` and `ytm.py` |
| A chat command misbehaves | `bot/commands/` (`user_commands.py`, `admin_commands.py`, `__init__.py`) |
| TeamTalk connection, messages | `bot/TeamTalk/`, `TeamTalkPy/TeamTalk5.py` |
| Gemini AI commands | `bot/ai/` |
| Config and updates | `bot/config/`, `bot/migrators/`, `bot/updater.py` |
| Installing FFmpeg / the TeamTalk SDK | `tools/setup_deps.py`, `install_windows.bat`, `install.sh` |
| Translations | `locale/`, `tools/compile_locales.py` |

## 6. Working rules that prevent trouble

- **One bug per session.** Start a fresh conversation for the next one. A long
  conversation drifts and the AI starts to confuse earlier guesses with facts.
- **Evidence over confidence.** Ask it to separate *proven by the log or the code* from
  *hypothesis*. A fix built on a hypothesis must say so, and you test it.
- **Verify outside facts yourself.** Package names, API fields, version numbers,
  model names and URLs come from official pages, not from the AI's memory. Examples
  that were checked while writing this project: the TeamTalk SDK download page
  (<https://bearware.dk/?page_id=419>) and API documentation
  (<https://bearware.dk/teamtalksdk/>), the Gemini model list
  (<https://ai.google.dev/gemini-api/docs/models>), and the Python release notes
  (<https://docs.python.org/3/whatsnew/>).
- **A test first.** If the AI cannot write a test that fails before the fix and passes
  after it, treat the fix as a guess.
- **Read the diff.** Reject changes you do not understand, and anything outside the
  bug. Ask for the diff to be split if it is large.
- **Keep the line endings.** Some files use CRLF (`bot/commands/__init__.py`,
  `bot/TeamTalk/__init__.py`) and `bot/player/track.py` mixes both. Tell the AI to keep
  each file's line endings, or the whole file shows as changed in git.
- **Python 3.15 rules (the bot supports 3.10 to 3.15).** Never call `load_module()`
  (removal list of 3.15): use `bot.utils.load_python_module()`. Never write the `lazy`
  keyword; a module that wants lazy imports declares `__lazy_modules__ = ["name"]`
  *before* the imports (a plain list on older versions). `tests/test_python_compat.py`
  fails on removed modules, deprecated calls, a missing `encoding=` and a broken
  `install_windows.bat`.
- **Keep text encodings explicit.** Always write `open(path, encoding="utf-8")`. Python
  3.15 made UTF-8 the default, but older versions on Windows still use the system
  code page.
- **User-visible text goes through the translator** (`self.bot.translator.translate(...)`
  or `translate(...)`). After you add a string, update the `.po` files and run
  `python tools/compile_locales.py`; `tests/test_locales.py` fails when a `.mo` is out
  of date.
- **No secrets in prompts or commits.** Cookies, API keys and `config.json` stay local.

## 7. Prompts that are worth reusing

Explain before editing:

```text
Do not edit anything yet. Explain how <feature> works, naming the functions in order,
and mark anything you are guessing.
```

Review a change you or someone else made:

```text
Here is my diff. Look only for regressions and for behaviour that changed without being
mentioned. For each finding give the file and line, and say whether you are certain.
```

Check a claim:

```text
You said <claim>. Show the exact line of code or the official documentation page that
proves it. If you cannot, withdraw the claim.
```

Write the changelog entry:

```text
Write a CHANGELOG entry for this change in the style of the existing entries: what was
wrong (symptom), the cause, what changed, which tests were added. No marketing words.
```

## 8. Before you open a pull request

- [ ] The change fixes the one bug you described, and nothing else.
- [ ] A test fails without the change and passes with it.
- [ ] `python tools/run_tests.py` (Windows: `run_tests.bat`) ends with ALL TESTS PASSED.
      The tests need `pydantic` and the other requirements installed, but not the TeamTalk
      library (`tests/__init__.py` loads the bot with a stand-in for it).
- [ ] New user-visible strings are translated and the `.mo` files are compiled.
- [ ] `CHANGELOG.md` says what changed, and the version in `bot/app_vars.py` is only
      raised when a release is intended.
- [ ] No secrets, cookies or personal server details in the diff or the log excerpts.
- [ ] Anything the AI stated as fact about an outside system has been checked against
      the official source.
