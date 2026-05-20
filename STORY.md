# How this project was made

## Background

I bought a pair of Shokz bone-conduction headphones for swimming. They support local MP3 playback. I wanted to listen to audiobooks while swimming. The audiobooks I want are on Ximalaya, a Chinese audio content platform. Ximalaya's desktop client downloads its content as `.xm` files — an encrypted format that isn't playable on anything else.

I needed to convert `.xm` files to `.mp3` to put them on the headphones.

## Constraints

- The content was already legally purchased on Ximalaya. The conversion is for personal device migration, not redistribution.
- I only have a Mac.
- I don't write code.

## Looking for existing tools

I searched on GitHub. Two relevant projects existed:

- [sld272/Ximalaya-XM-Decrypt](https://github.com/sld272/Ximalaya-XM-Decrypt): The reference Python implementation. Author archived it in August 2025. It's a CLI tool. No GUI, no batch folder support.
- [jupitergao18/xm_decryptor](https://github.com/jupitergao18/xm_decryptor): A Rust rewrite. The author explicitly notes they rewrote it because the original Python version couldn't be installed on their Windows Python 3.11 environment. Only ships a Windows binary.

Neither was usable on Mac out of the box. Both were designed to process one file at a time. Ximalaya downloads come in album folders containing dozens to hundreds of `.xm` files, so one-at-a-time processing is impractical.

## Plan

Take the existing decryption logic and wrap it in:

1. A drag-and-drop GUI that accepts a folder
2. Automatic batch processing
3. Automatic `.m4a → .mp3` conversion via ffmpeg

I didn't write any of the code myself. The entire implementation was done through natural-language conversation with Claude in a chat window (not Claude Code or any agent — just the regular chat interface). I copy-pasted commands the model gave me into the terminal, reported the output back, and iterated.

## Time spent

About 3.5 hours from initial search to public GitHub release. The chat-window approach is slower than using an agent like Claude Code — every command requires manual copy-paste and result reporting — but it works.

## What broke and what didn't

The original Python project depended on the `wasmer` Python library, which has been unmaintained since 2022 and doesn't install on current macOS / Python 3.11+. This is the same reason the Rust rewrite exists. Claude swapped it for `wasmtime` (actively maintained) with a one-to-one API translation. The replacement worked on the first run.

Other issues encountered, all resolved without changing the core decryption logic:

- macOS Gatekeeper blocked the launch script. Solved by user-side "Open Anyway" instruction.
- Python's bundled OpenSSL had no CA bundle, so `pip install` failed with SSL errors. Solved by passing `--trusted-host` to pip in the launch script.
- `python-magic` required `libmagic` as a system dependency, which most Mac users don't have. Solved by removing the dependency entirely and identifying audio formats by reading file header bytes directly.
- libmagic returned `"ISO Media"` instead of `"m4a"` on the test machine, breaking the original format detection. Caught during testing and replaced with header-byte detection (above).
- `ffmpeg` is not installed by default on macOS. The launch script now auto-downloads a static Apple Silicon build from osxexperts.net with SHA-256 verification.
- GitHub push failed due to network issues from China. Resolved by routing git through the local proxy port.

The interesting result: every decryption attempt on real `.xm` files worked on the first try. Zero correctness bugs in the actual core logic, despite the swap of WASM runtime and despite the original Python project being archived and partially broken on modern systems.

## What I contributed

- Identifying the problem (Shokz needs MP3, Ximalaya gives XM, no Mac tool exists for batch)
- Specifying the product (drag a folder, get MP3s, default output to Desktop)
- Testing on real files
- Deciding what gets packaged, what goes in the README, what gets cut
- Handling the GitHub publishing process

## What I did not contribute

- Any code, including the WASM runtime swap, the GUI implementation, the launch script, the file-header format detection, and the README itself
- The decryption algorithm (sld272/Ximalaya-XM-Decrypt)
- The reverse engineering of the XM format ([@aynakeya](https://www.aynakeya.com/))

## Tools used

- Claude (Anthropic), chat interface
- Terminal (manual copy-paste of commands)
- Finder, browser, GitHub web UI
- PandaFan (proxy, for the push step)

No IDE, no code editor, no command-line beyond pasting given commands.
