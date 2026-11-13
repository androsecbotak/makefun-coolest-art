# Make the coolest art — make.fun bounty entry

A deterministic, standard-library-only Python program that draws one cool
picture — a neon cyber-samurai under a blood-red sun — and writes it to
`output/entry.png` (1024x1024).

No network, no randomness, no third-party libraries: the PNG encoder is
written by hand on top of `zlib` (stdlib). Two runs produce byte-identical
output.

Run it:

```sh
python3 main.py
```
