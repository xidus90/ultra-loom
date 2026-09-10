# Offene Aufgaben, Spezifikationen und Pläne (Status-Tracker)

**Stand:** 2026-09-10, nach dem Arbeitsdurchgang des Tages (Zweigabbau,
Cherry-Picks, `ulinit check types`)
**Haupt-Checkout:** [`master`](file:///c:/Users/micro/Documents/%23GIT/ultraloom) — Basis ist `origin/master` = `d744a0c`; den Stand mit `git log --oneline origin/master..master` lesen. Eine Zahl an dieser Stelle veraltet mit dem Commit, der sie einträgt

Diese Übersicht führt die aktiven Stränge, Zweige, Worktrees und offenen
Arbeitspakete im Repository `ultraloom`. Abgeschlossenes wird über die
Checkboxen (`- [x]`) abgehakt.

Sie ersetzt kein Wiki — nur steht unter [`docs/wiki/`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki)
bisher nichts: `index.md`, `log.md` und `audit.md` sind leere Vorlagen mit einem
Merksatz, `_identities.tsv` trägt nur seine Kopfzeile. Was in diesem Repo
dauerhaft gilt, steht heute in `README.md`, `AGENTS.md` und den Ablaufseiten
unter [`docs/flows/`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/flows).
Das Füllen des Wikis ist selbst ein offener Punkt — siehe Abschnitt 6.

> [!NOTE]
> **Zur Sprache dieser Datei.** `AGENTS.md` verlangt für Dokumentation ein
> englisches Original mit einem `.de.md` daneben. Diese Datei folgt stattdessen
> den Schwesterdateien in `space` und `ultra-brain` und steht nur auf Deutsch.
> Ein Statustracker ist ein Arbeitspapier wie die Dateien unter
> `docs/.superpowers/`, die von der Regel ausgenommen sind.

---

## 1. Aktive Zweige, Worktrees und ihr Stand

| Strang / Fokus | Branch | Worktree-Pfad | Status | Aktiver Stand | Nächste Aktion |
|---|---|---|---|---|---|
| **Worktree-Spiegel (Junctions für git-ignorierte Verzeichnisse)** | `master` | [Hauptverzeichnis](file:///c:/Users/micro/Documents/%23GIT/ultraloom) | 🟢 **gemergt** | `be16705` mergte den Strang. Zweig und Worktree sind bereits abgebaut | Die parkierten Nachläufer abarbeiten (Abschnitt 2). Das Ledger ist eingeordnet |
| **MCP-Server nativ statt über uv** | `claude/mcp-native` (gelöscht) | `.worktrees/mcp-native` (entfernt) | ✅ **erledigt** | **0 eigene Commits**, 35 hinter master — die Spitze `b82ab51` ist per `git merge-base --is-ancestor` als Vorfahr von `master` bestätigt. Worktree und Zweig am 2026-09-10 abgebaut | keine — der Strang ist geschlossen |
| **GDScript-Bahn dort fahren, wo der Godot-Baum steht** | `claude/brain-lint-braucht-ziel` (gelöscht) | — (kein Worktree) | ✅ **erledigt** | **0 eigene Commits**, 38 hinter master — `3433e6f` ist per `git merge-base --is-ancestor` als Vorfahr von `master` bestätigt. Zweig am 2026-09-10 gelöscht | keine — der Strang ist geschlossen |
| **Konsolenkodierung: Befunde, die cp1252 nicht schreiben kann** | `claude/jovial-panini-eedcc1` (existiert nicht mehr) | — (kein Worktree) | ✅ **erledigt** | **Am 2026-09-10 nachgemessen:** der Zweig ist weg (`git branch -a` kennt ihn nicht mehr), und der Inhalt liegt in `master`. `9032b14` ist **kein** Vorfahr von `master`, aber `d0780c5` trägt denselben Betreff, dasselbe Autordatum (2026-08-27 12:53 +0200) und dieselbe Änderung an `src/ultraloom/cli.py` (+19) und `tests/test_cli.py` (+51) — der Zweigcommit, auf `master` neu abgespielt. Beweis im Baum: [`src/ultraloom/cli.py:58`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/src/ultraloom/cli.py) sagt `stream.reconfigure(errors="replace")`, Zeile 52 begründet die Regel | keine. Der frühere Befund („der Fix ist nicht in master", `cli.py` kenne weder `reconfigure` noch `errors="replace"`) war zum damaligen Stand 2026-09-10 09:03 **richtig** und ist seit `d0780c5` überholt |
| **Audit-Nacharbeit (Tore, Multi-Marker, Aufräumen)** | `feat/audit-nacharbeit` | — (kein Worktree) | ✅ **erledigt** | **Am 2026-09-10 beide Commits auf `master` übernommen:** `e2c4911` als `94e2c2b` (Spec, 394 Zeilen) und `90d3e50` als `d941d26` (`cmd/init/run.go` +57, `cmd/init/run_test.go` +74). Beide Cherry-Picks liefen ohne Konflikt (Auto-Merge). Danach `ultraloom check all`: Exit 0 — ruff, `ulinit check gofmt`, `go vet`, dmypy, 920 Python-Tests, `go test ./...`, Python-Coverage 100 %, Go-Coverage 98,4 %. **Das frühere Urteil, `90d3e50` sei zu verwerfen, war falsch begründet** — der Commit fasst keine `.gitignore` dieses Repos an, sondern ergänzt in `cmd/init` eine Behandlung, die `master` gar nicht hatte (`grep` nach `gitignore` in `cmd/init/*.go` fand dort nichts); die Ausnahme `!/.ultra-brain/config.toml` war unberührt | **Offen: der Zweig selbst.** Cherry-Picks sind keine Vorfahren, `git branch -d` verweigert also — der Abbau bräuchte `-D`, und das ist eine Nutzerentscheidung |
| **Mehrere LLM-Anbieter** | `feature/multi-provider-llm` | [`.worktrees/multi-provider-llm`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/.worktrees/multi-provider-llm) | 🟠 **weit veraltet** | **155 eigene** Commits, **399 hinter** master, letzter Stand 2026-08-24 | Entscheiden, was davon noch trägt. Der Entwurf lebt nur auf dem Zweig; ein Rebase über 399 Commits ist kein Selbstläufer |

> [!IMPORTANT]
> **Zu parallelen Sitzungen — die Falle dieses Repos ist eine andere als in `space`.**
> Ein Verzeichnis unter `.claude/worktrees/` ist **nicht** notwendig ein
> Git-Worktree. Wer dort arbeitet, teilt Index und HEAD mit dem Haupt-Checkout:
> `git status` antwortet leer, `git add` überspringt neue Dateien wortlos.
> Die verlässliche Frage ist `git rev-parse --show-toplevel` beziehungsweise
> `git worktree list` — **nicht** `--git-dir` gegen `--git-common-dir`, dieser
> Vergleich liefert hier falsch positiv (siehe `CLAUDE.md`).
>
> Dazu die Regel vom 2026-08-25: **vor jedem Commit `git diff --cached --stat`
> lesen.** An jenem Tag nahm ein Commit hier fünf Umbenennungen einer fremden
> Sitzung mit — `git add <meine Datei>` war richtig, der Index hielt aber schon
> fremde Arbeit.

- [x] **`CLAUDE.md` war an einer Stelle veraltet — erledigt mit `8be2162`.**
      Der Befund vom 2026-09-10: die Seite nannte
      `.claude/worktrees/project-history-planning-cf98dc` als Beispiel eines
      echten Worktrees, obwohl `.claude/worktrees/` **leer** war und
      `git worktree list` nur `master`, `mcp-native` und `multi-provider-llm`
      kannte. `8be2162` („Date the worktree layout the argument rests on")
      schrieb den Absatz um: er datiert die Lage jetzt („as of 2026-09-10
      `git worktree list` names `.worktrees/mcp-native` and
      `.worktrees/multi-provider-llm`, and `.claude/worktrees/` is empty") und
      führt das alte Verzeichnis nur noch als ausdrücklich vergangenes
      Beispiel. Das Argument („der Pfad ist kein Beweis") stand ohnehin
      richtig — es ruht seither auf einem datierten Stand statt auf einem
      stillschweigend veralteten.

---

## 2. Strang: Worktree-Spiegel — gemergt, Ledger als Arbeitsspur eingeordnet

* **Spezifikation:** [2026-09-07-worktree-mirror-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-09-07-worktree-mirror-design.md)
* **Durchführungsplan:** [2026-09-07-worktree-mirror.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/plans/2026-09-07-worktree-mirror.md)
* **Ablaufseite:** [worktree-mirror.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/flows/worktree-mirror.md) / [.de.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/flows/worktree-mirror.de.md)
* **Ausführungsledger:** [sdd/2026-09-07-worktree-mirror/ledger.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/sdd/2026-09-07-worktree-mirror/ledger.md) — 52 KB, am 2026-09-10 dorthin verschoben, **weiter ungetrackt** (`.gitignore:2`)

Acht Tasks, alle abgeschlossen, Schlussreview „BRANCH READY FOR MERGE",
gemergt mit `be16705`.

- [x] Tasks 1–8 samt Fix-Runden, Re-Reviews und Schluss-Fix-Welle
- [x] Die elf Plantext-Korrekturen sind mit `e22eff2` und `9547320` in Plan und Spec eingetragen
- [x] Die zwei beim Schlussreview parkierten Minors sind mit `d744a0c` **doch noch** geschlossen: die Zeilenangabe in beiden Ablaufseiten steht auf `worktree_test.go:1078-1102`, und `link`s Docstring nennt jetzt beide Routen statt einer
- [x] **Das Ledger bleibt eine Arbeitsspur — entschieden am 2026-09-10.**
      Am 2026-09-10 nach
      `docs/.superpowers/sdd/2026-09-07-worktree-mirror/ledger.md` verschoben —
      und damit **nachgemessen, dass die Vorbildannahme dieses Punktes falsch
      war**: `.gitignore:2` ignoriert `docs/.superpowers/sdd/` vollständig, mit
      der Begründung „Work traces of plan execution: intermediate states of
      commits that follow". `git ls-files docs/.superpowers/` kennt unter `sdd/`
      keine einzige Datei, auch nicht den `crlf-fix-report.md` des
      Installer-Kern-Strangs. Das Verzeichnis war also nie ein *Ablageort für
      Eingechecktes*, sondern der Ort, an dem Arbeitsspuren liegen bleiben.
      Die Frage war damit, ob das Ledger eine Arbeitsspur ist oder eine
      Übergabe. **Entschieden am 2026-09-10: eine Arbeitsspur.** Es bleibt an
      seinem jetzigen Pfad ungetrackt liegen. Die Frage nach `handovers/` in
      Abschnitt 7 ist eine andere und bleibt offen.

### Was der Merge nicht mitgebracht hat

> [!WARNING]
> **Der Zweig merged inert — und das gilt am 2026-09-10 nur noch halb.**
> Die Verdrahtung, die damals „außerhalb dieses Repos" lag, existiert und ist
> committet: die globale `~/.claude/settings.json` hängt `worktree-link` an
> `SessionStart` (siehe den abgehakten Punkt unten). Was weiter fehlt, ist die
> **Konfiguration in diesem Repo**: `git grep "\[worktree\]" -- '*.toml'`
> findet keine einzige Deklaration — nur Prosa in `README.md` und Beispiele im
> Durchführungsplan. `.ultraloom/config.toml` hier deklariert keinen Spiegel.
> `ultraloom` benutzt seinen eigenen Spiegel also nicht, weil es ihm nichts zu
> spiegeln gibt, nicht weil der Mechanismus fehlt. Das bleibt eine offene
> Entscheidung, kein Defekt. Zum Vergleich: `space/.ultraloom/config.toml:28`
> deklariert `mirror = [".tools"]`.

- [x] **Die zweite Hälfte von Task 7 ist getan — am 2026-09-10 gefunden, nicht
      gebaut.** Die globale `~/.claude/settings.json` trägt
      `ulguard worktree-link --root "${CLAUDE_PROJECT_DIR}"` auf `SessionStart`
      und `worktree-unlink` auf `SessionEnd`, beide mit `timeout: 20`. Die
      Vorbedingung ist auch erfüllt: `ulguard` und `ulinit` liegen maschinenweit
      in `~/go/bin` (samt Bash-Shim ohne `.exe`), und
      `ulguard worktree-link --root <dieses Repo>` läuft mit Exit 0.
      **Warum dieses Dokument es nicht sehen konnte:** `~/.claude` ist ein
      eigenes Git-Repo, und der Eintrag lag dort uncommittet im Arbeitsbaum.
      Committet ist er seit `f5ece34` in jenem Repo — nicht in diesem.
- [ ] `.claude/settings.json` dieses Repos trägt **keinen** `worktree-link`-Hook
      — am 2026-09-10 nachgezählt, `grep -c worktree-link` antwortet **0**.
      Darin stehen `ulguard --root`, `ulguard post-edit --root`, vier
      `uv run --project`-Aufrufe und seit heute ein `brain guard` (siehe
      Abschnitt 5, das ist Fremdarbeit im Baum). Solange das so ist, heilt hier
      kein Sitzungsstart irgendwelche Junctions. **Es macht aber auch nichts**,
      solange die `config.toml` dieses Repos keinen Spiegel deklariert — die
      beiden offenen Punkte hängen zusammen und gehören gemeinsam entschieden.
- [x] **Die `space`-Worktrees sind verlinkt — am 2026-09-10 nachgesehen, und
      die Zahl war auch falsch.** Nicht vier, sondern **zwei** sind registriert
      (`git worktree list`: `.worktrees/mcp-native`, `.worktrees/okf-bundle-root`),
      und **beide tragen `.tools`** als Verweis auf
      `#GIT/space/.tools` des Haupt-Checkouts.
      **Was das nicht beweist:** die Zeitstempel der beiden Verweise sind
      2026-09-07 11:00 und 22:32, also älter als der globale Hook. Sie wurden
      während des Strangs selbst angelegt, nicht von einem Sitzungsstart
      geheilt. Der Punkt ist erledigt, weil nichts zu heilen ist — nicht, weil
      die Heilung beobachtet wurde. Ein echter Beweis bräuchte einen Worktree,
      dem der Verweis fehlt, und einen Sitzungsstart darin.

### Nachläufer, die das Schlussreview bewusst hat liegen lassen

- [ ] **`sameDir` liegt dreifach:** [`cmd/guard/worktree.go:519`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/cmd/guard/worktree.go),
      [`internal/worktreetopo/worktreetopo.go:160`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/internal/worktreetopo/worktreetopo.go),
      [`internal/junction/junction_test.go:21`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/internal/junction/junction_test.go).
      Die Zusammenlegung als exportiertes `worktreetopo.SameDir` war der
      Reviewbefund „Important 5" und wurde aus der Fix-Welle **herausgehalten**,
      weil ein Refactor unmittelbar vor dem Merge Risiko für Ordnung kauft.
- [ ] **`cli` verdrahtet `os.Stdout` an vier Stellen** ([`cmd/guard/main.go:23,43,53,68`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/cmd/guard/main.go)),
      deshalb lässt sich der Schweigevertrag durch `cli` hindurch nicht prüfen
      („Important 4", ebenfalls herausgehalten).
- [ ] **Der Flagset-Block steht fünfmal in `main.go`** (gezählt:
      5 × `flag.NewFlagSet`). Ein `subcommand()`-Helfer ist die Aufräumarbeit,
      dreimal über die Tasks 4, 5 und 6 vertagt.
- [ ] **Der Sitzungs-Cutoff schließt das Loch nicht** — weder 24 Stunden noch
      irgendeine andere Zahl. Der echte Fix ist ein Schreibvorgang auf der
      lebenden Seite: `worktree-link` fasst die Zustandsdatei der Sitzung beim
      Start an, oder es wird von `SessionEnd` aus geschrieben. Steht so auch in
      [`docs/flows/worktree-mirror.md`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/flows/worktree-mirror.md): „is not built".
- [ ] `registeredAs` dupliziert die Schleife aus `Topology.registered`; eine
      Methode auf `Topology`, die die getroffene Schreibweise zurückgibt, hielte
      den Vergleich im Paket, dem er gehört.
- [ ] Ein Fehler im Sweep bricht die Schleife ab: bei zwei schlechten Pfaden
      wird nur der erste genannt, und eine unlesbare Zwischenkomponente in einem
      **früheren** Spiegeleintrag verhindert das Anlegen eines späteren
      gesunden (etwa `.ultraloom/vendor`, die gepinnte Laufzeit). Laut, nicht
      still — der nächste `worktree-link` versucht es erneut.
- [x] Die Überlebensmeldung behauptete eine **Ursache**, die `os.Lstat` nicht
      belegen kann. **Nachgerechnet: erledigt** —
      [`cmd/guard/worktree.go:238`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/cmd/guard/worktree.go)
      sagt heute „nothing here removed it", einen Befund statt einer Ursache.
- [ ] Eine Anweisung bleibt vermutlich ungedeckt: `return err` nach
      `junction.Remove` in `cmd/guard`. Drei ACL-Versuche sind dokumentiert; der
      deterministische Weg braucht ein offenes Handle über `x/sys` und die erste
      `_windows_test.go` in `cmd/guard` — die gibt es dort nach wie vor nicht
      (nur `internal/junction/junction_windows_test.go`). Die Schluss-Fix-Welle
      hat den `os.Remove`-Zweig in `junction.Remove` selbst gedeckt, nicht
      diesen Aufrufer.
- [ ] `TestCliDispatchesWorktreeUnlink` benutzt einen bereits geleerten
      Payload-Leser wieder — es läuft nur, weil das Flag-Parsen scheitert, bevor
      stdin gelesen wird. Zerbrechlich, nicht falsch.
- [ ] Das Konventionsverzeichnis selbst (`.worktrees`, `.claude/worktrees`) deckt
      `standsInside` nicht ab: wäre **es** eine Junction, folgte `os.ReadDir` ihr
      und zählte ihre echten Unterverzeichnisse als Waisen dieses Repos.

---

## 3. Strang: Dokumentation gegen den Code nachrechnen (laufend)

Der Strang läuft weiter und hat am 2026-09-10 einen zweiten Schub bekommen.
Immer dieselbe Bewegung: eine Behauptung in der Doku wird gegen den Code
gemessen und entweder korrigiert oder als datierter Befund stehengelassen.
Keine Gesamtzahl hier — `git log --oneline origin/master..master` sagt sie.

- [x] Die generierten Hooks rufen das `ultraloom` auf dem PATH (`bd6feef` —
      neben `d0780c5` eine der zwei Codeänderungen des Strangs, in `cmd/init`)
- [x] Sagen, was für den Befehl gilt, über dem der Docstring steht (`9374b92`)
- [x] Sagen, wann das von den Hooks gerufene `ultraloom` nicht auf dem PATH ist (`c1f7333`)
- [x] Die Hooks so zählen, wie `hookEntries` sie schreibt (`8294b33`)
- [x] `hookCommand` beim Namen nennen, und die Zahl, die nicht zurückgezogen wurde (`f0bddb3`)
- [x] Den Policy-Erzwinger nennen, der wirklich läuft (`7c1a879`)
- [x] Befunde melden, die die Konsole nicht kodieren kann (`d0780c5` — die
      zweite Codeänderung des Strangs, `cli.py` und `tests/test_cli.py`; siehe
      Zeile 4 der Matrix in Abschnitt 1)
- [x] Die Worktree-Lage datieren, auf der das Argument ruht (`8be2162` — der
      `CLAUDE.md`-Fix am Ende von Abschnitt 1)

Zweiter Schub, 2026-09-10, aus dem Abarbeiten dieser Datei selbst:

- [x] Die Worktree-Lage **erneut** datieren, nachdem dieselbe Sitzung einen
      Worktree entfernt hatte (`b8d0811`). `8be2162` schrieb morgens „as of
      2026-09-10 … names `.worktrees/mcp-native` and
      `.worktrees/multi-provider-llm`" — und wenige Stunden später war
      `mcp-native` abgebaut. Der Absatz ist das eigene Argument am eigenen
      Beispiel: wer eine Lage benennt, datiert seinen Satz.
- [x] Diesen Tracker einchecken, samt der vier Behauptungen, die er selbst
      nicht hielt (`298b473`)
- [x] Keine Commitzahl mehr in eine Datei schreiben, die ein Commit ändert
      (`b722283`) — sie stand zweimal falsch darin, im Kopf und in Abschnitt 5
- [x] Aufschreiben, worauf die `types`-Bahn gemessen wurde, in beiden Sprachen
      (`617e2ab`)
- [x] Sagen, dass die dmypy-Heilung Windows-only ist und Raten sie nicht
      reparieren würde (`dcf8fca`)
- [x] Task 7s zweite Hälfte schließen, die in einem Repo getan war, das diese
      Datei nicht sehen kann (`b95c187`)

### Zwei dokumentierte Lücken, die als Befund stehen

- [ ] **`ultraloom policy check <kind> <value>` wurde nie gebaut.** Der
      README-Abschnitt „Policy" beschrieb eine Handform, die es nicht gibt;
      `ulguard check …` ist kein Unterbefehl, sondern fällt in den
      Payload-Leser und antwortet mit Exit 1. Der Satz steht seit `7c1a879`
      als datierter Befund in [`README.md:424-429`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/README.md)
      statt gelöscht zu sein — **die Entscheidung, ob die Fähigkeit gebaut oder
      der Abschnitt entfernt wird, ist offen.**
- [ ] **Der Rest des Policy-Abschnitts weicht in fünf Punkten vom Code ab**,
      jeder am selben Tag gemessen und im README benannt. Die Prosa ist noch
      nicht nachgezogen.
- [x] Die Zahl „fifteen" in
      [`docs/flows/verify-until-green.md:675`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/flows/verify-until-green.md)
      — **kein offener Punkt:** der Satz ist ein datierter Befund, und die
      Korrektur steht direkt dahinter („the count below comes out to fourteen").

---

## 4. Strang: Backlog aus Teilprojekt 1 und 2

* **Datei:** [2026-08-21-teilprojekt-2-backlog.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-21-teilprojekt-2-backlog.md)

> [!NOTE]
> Die Datei sammelt in **drei Runden** (Teilprojekt 1, Teilprojekt 2, Umbau der
> Prüfkette), was gesehen, beurteilt und mit Begründung verschoben wurde. Sie
> wird mitgepflegt: mehrere Punkte tragen bereits ein **ERLEDIGT** mit Verweis
> auf die Spec, die sie umgesetzt hat. Nur diese Erledigt-Vermerke sind unten
> ausgewertet — **gegen den heutigen Code nachgerechnet ist keiner der offenen
> Punkte**, also vor dem Anfassen erst prüfen, ob er noch besteht.

### Runde 1 — aus Teilprojekt 1

- [x] **Zeitgrenze für Prüfkommandos** — umgesetzt über `process.run`
      (`Popen` in eigener Prozessgruppe bzw. Job-Objekt, Baumtötung bei
      Fristablauf, zweites kurzes Sammelfenster). Damit ist auch das
      Enkelproblem erledigt.
- [ ] **Der Journal-Cache ist unbedingt.** Ein Knoten mit einem `ok`-Eintrag
      unter `(Name, input_hash)` liefert dessen Delta zurück, auch außerhalb des
      Wiedergabemodus. Ein begrenzter Zyklus ist damit wirkungslos, wenn seine
      Nutzlast sich nicht ändert. Wenn Wiederholschleifen gebraucht werden, ist
      das die erste Frage.
- [ ] **Schema-Semantik des Modell-Adapters:** wie reichhaltig `AgentNode.schema`
      sein darf — verschachtelte Dataclasses, Listen, Optionals.
- [ ] **`mcp__<server>` ohne Werkzeugsegment.** Abgeleitet aus dem Parser des
      SDK, nie gegen einen laufenden MCP-Server gemessen.
- [ ] **Der Contract-Test ist nie gelaufen** (`uv run pytest -m contract`) — er
      braucht Zugangsdaten und Netz. Solange das offen ist, ist die
      Token-Abrechnung unbestätigt: `usage.get("output_tokens", 0)` liefert bei
      einer Umbenennung still Kosten von 0.
- [ ] **Committet der Reparateur, sieht die Wache nichts.** `guard` misst über
      `git status`, also über den Arbeitsbaum. Ein Agent, der committet,
      hinterlässt einen sauberen Baum — eine geänderte Testdatei geht durch.
      Heute nur entschärft: das Werkzeugprofil `edit` enthält kein Bash. Die
      härtere Grundlage wäre der Vergleich gegen einen beim Laufstart
      festgehaltenen Ausgangs-Commit.
- [ ] **Das Pausenfenster gehört niemandem.** Ändert ein Mensch zwischen `run`
      und `resume` eine geschützte Datei, lastet die Wache das dem Reparateur an
      (Exit 4 gegen einen Unschuldigen). Scharf, sobald Teilprojekt 4 die
      Gate-Variante der Testsperre baut.

Kleinere Punkte derselben Runde: `_why_it_looped` erklärt die Besuchsgrenze erst
beim Erreichen; eine Antwort mit unerreichbarem Pause-Hash wird still verworfen;
`list_flows` verschweigt eine Datei wie `my-flow.py`, statt sie zu erklären;
`tests/test_config.py` trägt einen redundanten Grenztest; `flows/__init__.py`
ist ein leeres Paket.

### Runde 2 — aus Teilprojekt 2

- [x] **`claude-agent-sdk` ist nicht gepinnt** — erledigt: das Extra nennt
      `claude-agent-sdk==0.2.143`, und `run` prüft vor dem ersten Knoten, ob eine
      startbare CLI erreichbar ist.
- [ ] **`setting_sources` bleibt ungesetzt** im Adapter (`model/agent_sdk.py`).
- [ ] **Ein Exit-Code ist das ganze Urteil — manche Prüfwerkzeuge kennen ihn
      nicht.** Teilweise erledigt (die Mechanik steht), der Rest offen.
- [x] **Eine Prüfart, ein Kommando** (`config._KINDS`) — erledigt, mehrere
      Kommandos je Art sind gebaut.
- [x] **Zwischen Prüfungen gibt es keine Reihenfolge** (Spec 9.4) — erledigt.
- [ ] **Stille Präzedenz bei Coverage.** `resolve_check` prüft
      `config.coverage_report` **vor** `config.commands`; wer beides setzt,
      bekommt ohne Warnung das erste. Offen ist, wie viel `load_config`
      beurteilen darf.
- [ ] **`[verify.coverage].threshold` wird nicht durchgesetzt** — gelesen,
      weitergereicht, aber kein Kommando bekommt sie. Offen: ob der Schlüssel
      überhaupt bleiben soll. **Betrifft dieses Repo unmittelbar:** die
      `config.toml` hier setzt `threshold = 100`.
- [ ] **Der Beweis für die Testsperre fehlt.** Fünf Läufe in zwei Projekten
      haben versucht, einen echten Agenten an eine Testdatei zu bringen; keiner
      hat es geschafft. Unit-getestet, gegen ein echtes Modell unbewiesen.

### Runde 3 — aus dem Umbau der Prüfkette

- [ ] **Der POSIX-Zweig von `process.py` ist nie ausgeführt worden.**
      `_terminate_posix` trägt `# pragma: no cover  # POSIX-only` und ist auf
      dieser Maschine nie gelaufen. Die Hälfte der Plattformweiche ist
      Behauptung. **Oberster Punkt dieser Runde** — er braucht eine
      POSIX-Maschine.
- [ ] **Ein Journal von vor dem Umbau passt nicht mehr auf seinen `check`-Knoten.**
      `VerifyState` hat `blocked` und `brief` dazubekommen, beide gehen in den
      `input_hash`. Ein laufender Auftrag führt den Knoten nach dem Upgrade neu
      aus — bezahlte Token für getane Arbeit. Was fehlt, ist die Meldung.
- [ ] **Restfenster bei der PID-Wiederverwendung unter Windows.** Ein
      Fremdprozess, der nach der Wurzel geboren wird und eine recycelte PID aus
      unserem Baum als Eltern-PID trägt, würde mitgetötet. Wahrscheinlichkeit
      winzig, Schaden aber einer, den niemand mit ultraloom in Verbindung
      brächte.
- [ ] **Godot hat kein `coverage`-Preset**, und das kostet jedes Godot-Projekt
      eine Zeile Konfiguration. Bewusst so — ein erfundenes Preset hätte nach
      einer Prüfung ausgesehen, ohne eine zu sein.

---

## 5. Übergreifend: Repo-Zustand und Prüfketten

### Git

- [ ] **Ungepusht ist alles zwischen `origin/master` (`d744a0c`) und `master`.**
      Keine Zahl hier: sie war in diesem Dokument schon zweimal falsch, weil der
      Commit, der sie einträgt, sie selbst widerlegt. `git log --oneline
      origin/master..master` ist die Antwort. Was das Remote erreicht, entscheidet der
      Nutzer — siehe `CLAUDE.md`. Kein Subagent pusht; nach einem Subagentenlauf
      wird `git ls-remote origin <branch>` gelesen, nicht dem Bericht geglaubt.
- [x] **Der Zweigabbau ist gelaufen.** Am 2026-09-10 sind
      `claude/mcp-native` und `claude/brain-lint-braucht-ziel` gelöscht, beide
      ohne eigene Commits und ihre Spitzen als Vorfahren von `master`
      bestätigt. Der dritte Kandidat, `claude/jovial-panini-eedcc1`, war zu
      diesem Zeitpunkt schon weg. Damit stehen **zwei Zweige neben `master`**:
      `feat/audit-nacharbeit` und `feature/multi-provider-llm` — siehe Matrix
      oben. `feat/audit-nacharbeit` ist inhaltlich erledigt (beide Commits am
      2026-09-10 cherry-gepickt), aber als Cherry-Pick kein Vorfahr: sein
      Abbau bräuchte `git branch -D` und steht noch aus.
- [x] **Ein Worktree** mit sauberem Arbeitsbaum
      (`.worktrees/multi-provider-llm`); `.worktrees/mcp-native` ist am
      2026-09-10 mit dem Zweigabbau entfernt worden.
- [ ] **Untrackt im Baum, Stand 2026-09-10 nach dem Ledgerumzug:** diese
      Datei hier, das Ledger (jetzt unter `docs/.superpowers/sdd/`, dort per
      `.gitignore:2` gewollt ungetrackt) — und dazu ein Satz Dateien, die
      **keine Sitzung dieses Strangs geschrieben hat**. Am 2026-09-10
      nachgesehen: es sind **zwei** Verursacher, nicht einer.
      - Um **10:57** hat ein Wiki-Indexer über den Baum geschrieben, mit
        `"scope": "project/ultraloom"` in `graph.json`: dazu `index.md` im
        Wurzelverzeichnis und je eines in `docs/`, `docs/flows/`,
        `docs/.superpowers/`, `docs/.superpowers/plans/`,
        `docs/.superpowers/specs/`, sowie ein `_identities.tsv` im
        Wurzelverzeichnis mit **68 Einträgen** in genau dem Schema, das
        `docs/wiki/_identities.tsv` als Kopfzeile trägt
        (`doc_id`, `pfad`, `content_hash`, `revision`). Er hat seinen Katalog
        also **neben** `docs/wiki/` gelegt statt hinein.
      - Um **11:04** hat Obsidian `docs/wiki/.obsidian/` angelegt — die
        Vault-Konfiguration, die beim Öffnen des Verzeichnisses entsteht. Das
        ist eine andere Ursache als die erste und hat mit dem Indexer nichts zu
        tun.
      Dasselbe Werkzeug hat auch `.agents/hooks.json` und
      `.claude/settings.json` geändert, ohne dass eine Sitzung dieses Strangs
      es anfasste: beide tragen jetzt einen `brain guard`-Hook, in
      `.agents/hooks.json` unter Umbenennung des Wurzelschlüssels von `hooks`
      auf `wiki-guard` und mit `run_command` aus dem Matcher entfernt. Diese
      zwei Änderungen liegen am 2026-09-10 ungestaged im Baum und sind
      **nicht** mit den Commits dieses Tages gegangen. **Offen: ob sie so
      gewollt sind.**
      Der Indexlauf ist zugleich der Beweis, dass das leere Wiki aus
      Abschnitt 6 nicht unindiziert ist: der Katalog existiert, er liegt nur
      ungetrackt am falschen Ort. **Offen: ob der Indexer nach `docs/wiki/`
      umgelenkt wird und ob `.obsidian/` in die `.gitignore` gehört.**

### Zwei Binärstände, die driften

- [ ] **Der Checkout und der PATH tragen verschiedene Binärstände.** Die
      `config.toml` ruft `./ulinit`, die Hooks rufen das `ulinit` aus
      `~/go/bin`. Am 2026-09-10 kannte das PATH-Binär `check types` noch nicht,
      während der Checkout es hatte — ein Hook wäre an einem Unterbefehl
      gescheitert, der existiert. Beide sind jetzt gebaut, aber die Drift ist
      strukturell: **es gibt keinen Schritt, der beide zusammenhält.**
- [ ] **`go install` ist hier die falsche Waffe** und hat am 2026-09-10 zwei
      Streuner erzeugt. Es benennt das Ergebnis nach dem Paketverzeichnis, also
      `init.exe` und `guard.exe`, nicht `ulinit.exe` und `ulguard.exe`, die die
      Hooks rufen — exitet dabei mit 0 und lässt die alten Binäre unberührt.
      `go build -o <zielname>` ist der Weg; die Streuner sind entfernt. Offen:
      ob ein `Makefile`- oder `ulinit`-Schritt das übernimmt, statt es in einer
      Anweisungsdatei zu erklären.

### Zwei halbe Go-Formen in der `check`-Familie

Beim Bau von `ulinit check types` am 2026-09-10 mitgelesen; keiner der beiden
Punkte wurde angefasst.

- [ ] **`ulinit check coverage` gibt 0 zurück, wenn `--summary` leer ist**
      ([`cmd/init/check.go`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/cmd/init/check.go)),
      und `check_test.go` schreibt genau das fest. Es misst selbst nichts,
      sondern prüft nur eine Zeichenkette, die man ihm reicht — ein Tor, das
      grün meldet, wenn man ihm nichts gibt. Deshalb ruft die `config.toml`
      für `coverage` weiter das Python-Skript, obwohl der Go-Weg daneben liegt.
- [ ] **`ulinit check commit-msg` ist kein Ersatz für `ultraloom commit-msg`.**
      Die Go-Form ist eine festverdrahtete Wortlistenprüfung auf Englisch
      über nur die erste Zeile
      ([`internal/commit/language.go`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/internal/commit/language.go)),
      die Python-Form liest `[commit]`, kennt `--language en|de` und
      `--calibrate N`. Ein Projekt mit deutschen Commits zerbricht an der
      Umstellung. Offen: ob die Go-Form die Konfiguration nachbaut oder als
      bewusst engere Prüfung benannt wird.

### Prüfkette

Konfiguriert in [`.ultraloom/config.toml`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/.ultraloom/config.toml).
**Am 2026-09-10 ist die ganze Kette mehrfach gefahren, jedes Mal Exit 0** —
einmal von Hand als `ultraloom check all` und dann bei jedem der sechs Commits
des Tages als Commit-Gate. Die Angaben unten sind damit Messergebnis und nicht
nur Konfiguration: ruff sauber, `ulinit check gofmt` und `go vet` stumm, dmypy
grün, **920 Python-Tests** bestanden (1 deselektiert) und `go test ./...`
durchweg `ok`, Python-Coverage **100 %**, Go-Coverage **98,5 %**.

| Bahn | Befehle | Anmerkung |
|---|---|---|
| `lint` | `uv run ruff check .`, `./ulinit check gofmt cmd internal`, `go vet ./...` | nebenläufig; `gofmt -l` exitet auch bei Befund mit 0, deshalb der Umweg über `ulinit check` |
| `types` | `./ulinit check types` | Seit 2026-09-10 (`67a9f2b`) der Go-Shim statt `uv run dmypy run --` unmittelbar; er trägt die zwei mypy-Flags und räumt eine Statusdatei weg, die ihren Daemon überlebt hat. Daemon statt mypy: warm 1400 → 988 ms, kalt 9,6 → 9,1 s (A/B am 2026-08-27) |
| `test` | `uv run pytest`, `go test ./...` | nebenläufig |
| `coverage` | `uv run --script hooks/coverage-check.py 98.0` | Python über `fail_under`, Go-Boden **98,0** |
| Profile | `edit` = lint+types; `precommit` = lint+types+test+coverage | |

- [ ] **`precommit` fährt pytest zweimal.** Weil `test` konfiguriert ist, liest
      `coverage` nicht mehr, was die Suite hinterlassen hat, sondern misst
      selbst. Kosten bekannt und angenommen — ein grüner Bericht über alten
      Daten ist das eine, was nicht passieren darf.
- [ ] **Der Go-Boden ist eine Stolperdrahtgrenze, kein Ziel.** Gemessen am
      2026-08-28: 745 Anweisungen, 11 in zehn unerreichbaren Blöcken = 98,5 %.
      **Am 2026-09-10 zweimal nachgemessen: 98,4 % nach `d941d26`** (57
      Anweisungen in `cmd/init`, ein Zehntelpunkt Luft verbraucht), **wieder
      98,5 % nach `67a9f2b`**. Die zweite Zahl widerlegt die naheliegende
      Sorge: gut gedeckter neuer Code verdünnt die ungedeckten Anweisungen und
      **hebt** den Prozentsatz. Nur unerreichbare Zweige kosten. Gemessen waren
      es 2294 Anweisungen, 36 davon offen; der Boden 98,0 erlaubt 45 — also
      **neun Anweisungen Luft**, etwa drei weitere unerreichbare Fehlerzweige.
      **Anheben, wenn die Luft verbraucht ist — nicht weiten.**
- [x] **Die verwaiste `.dmypy.json` legt die `types`-Bahn nicht mehr lahm.**
      Gebaut am 2026-09-10 als `ulinit check types` (`67a9f2b`), und die
      `config.toml` ruft es statt `uv run dmypy run --`. Zwei Messungen haben
      den Entwurf dabei geändert, beide gegen die erste Annahme:
      - **Nur die Pipe-Meldung erreicht den Aufrufer von `dmypy run`.** `do_run`
        fragt `is_running()`, und das verschluckt jedes `BadStatus` und startet
        einen frischen Daemon — eine Statusdatei mit totem Pid heilt sich selbst
        und schreibt „Daemon started". Der Fall, der die Bahn umbringt, ist der
        andere: **lebendiger Pid, verschwundene Pipe.**
      - **Die Heilung darf nichts töten.** `dmypy kill` stand in der ersten
        Fassung und ist wieder heraus: der Pid in einer abgestandenen
        Statusdatei ist per Definition lebendig — deshalb wurde `is_running`
        getäuscht — und gehört fast immer dem, dem das Betriebssystem die
        recycelte Nummer gegeben hat. Unter Windows tötet dmypy über
        `taskkill /pid <n> /f /t`. **Gemessen: ein schlafender Shell-Prozess,
        dessen Pid in der Datei stand, überlebte die Heilung nicht.** Das ist
        derselbe Schaden, den dieses Dokument für `process.py` in Abschnitt 4,
        Runde 3 als offenen Punkt führt. Ohne `kill` überlebt er.
      Die Unterscheidung zwischen Befund und Defekt kommt von dmypy selbst: ein
      Urteil trägt mypys Status durch `check_output`, ein Daemonfehler verlässt
      `fail()` mit Exit 2. Exit 2 allein genügt nicht, weil ein blockierender
      Fehler auch 2 ist — deshalb zusätzlich eine der Meldungen aus mypys
      Quelltext. Go und kein Skript neben `hooks/coverage-check.py`, gemessen am
      2026-09-10 über 10 warme Läufe: `uv run --script` auf einem leeren
      PEP-723-Skript 55 ms Median, `ulinit` 31 ms — 24 ms an jedem Post-Edit,
      gegen eine Bahn, die es wegen eines A/B über 412 ms überhaupt gibt.
- [ ] **Ein Zeitflackern ist bekannt:**
      `test_check_all_waits_for_the_checks_at_the_same_time` war einmal unter
      Last rot (1,40 s), allein und im zweiten vollen Lauf grün.
- [ ] `[verify.coverage].threshold = 100` steht in der `config.toml`, wird aber
      nicht durchgesetzt — ultraloom druckt die Zahl nur, durchgesetzt wird, was
      `fail_under` in `pyproject.toml` und der Boden 98,0 im Report-Kommando
      sagen. Ein Leser der Konfiguration liest hier eine Anforderung, die keine
      ist. Siehe den Backlog-Punkt in Abschnitt 4, Runde 2.

---

## 6. Übergreifend: Das Wiki ist leer

`AGENTS.md` legt fest, wohin welches Wissen gehört: Projektwissen nach
[`docs/wiki/`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki),
übertragbares Wissen in einen geteilten Bereich, im Zweifel geteilt und aus dem
Projekt darauf verweisen. Umgesetzt ist davon nichts.

| Datei | Inhalt heute |
|---|---|
| [`docs/wiki/index.md`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki/index.md) | Überschrift „Katalog" plus ein Merksatz |
| [`docs/wiki/log.md`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki/log.md) | Überschrift „Protokoll" plus ein Merksatz |
| [`docs/wiki/audit.md`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki/audit.md) | „Gefüllt wird es ab Scheibe 5; bis dahin bleibt es leer" |
| [`docs/wiki/_identities.tsv`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/wiki/_identities.tsv) | nur die Kopfzeile |

- [ ] **Das Wiki ist als Datei leer, aber nicht unindiziert.** Am 2026-09-10
      um 10:57 hat ein Wiki-Indexer den ganzen Baum unter
      `"scope": "project/ultraloom"` erfasst — 68 Dokumente mit `sha256` in
      einem `_identities.tsv`, dazu `graph.json` und sechs `index.md`. Nur
      schrieb er das alles ins **Wurzelverzeichnis** und in die
      Dokumentordner, nicht nach `docs/wiki/`, und nichts davon ist getrackt.
      Die Tabelle **oben** beschreibt also die Vorlagen, nicht den
      Wissensstand. Siehe den Befund in Abschnitt 5.
- [ ] **Entscheiden, ob das Wiki hier überhaupt gefüllt wird.** Das Wissen dieses
      Repos steht heute in `README.md` (lang), `AGENTS.md`, `CLAUDE.md` und
      `docs/flows/`. Entweder das Wiki wird der Ort und die Ablaufseiten ziehen
      um, oder die drei Vorlagen sagen, was statt ihrer gilt.
- [ ] `audit.md` verweist auf „Scheibe 5" — eine Nummerierung, die in diesem Repo
      sonst nirgends vorkommt. Der Satz stammt vermutlich aus `ultra-brain`.
- [ ] **`docs/benchmarks.de.md` trägt eine Überschrift doppelt.**
      „Chronologisches Benchmark-Protokoll" steht dort zweimal, in der
      englischen Fassung einmal. Am 2026-09-10 beim Eintragen der
      `types`-Messung gesehen; der neue Eintrag steht unter der ersten. Die
      beiden Blöcke sind nicht chronologisch ineinander sortiert, sondern
      liegen hintereinander.
- [x] `docs/benchmarks.md` wird geführt, wie `AGENTS.md` es verlangt: die
      Messungen des Worktree-Spiegel-Strangs stehen drin — 2026-09-08 00:30
      (Kosten von `worktree-link` am Sitzungsstart, gemessen in `space` bei
      `43ece6f`) und 2026-09-08 15:05 (Python-Einstiegspunkt gegen das
      Go-Binary daneben) — und seit `617e2ab` auch die der `types`-Bahn vom
      2026-09-10, in beiden Sprachfassungen. Der neue Eintrag korrigiert
      dabei die Lesart des 15:05-Eintrags: seine ~253 ms sind der
      Python-**Paket**-Einstiegspunkt und dürfen nicht über `uv run --script`
      zitiert werden, das in einem Fünftel davon startet.

---

## 7. Ablage und Übergaben

- Nur **eine** Übergabe liegt unter
  [`handovers/`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/handovers):
  `2026-08-28-2019-installer-kern-merged.md`. Der Worktree-Spiegel-Strang, mit
  Abstand der größte seither, hat keine.
- [ ] Entscheiden, ob `handovers/` weitergeführt wird oder das Ausführungsledger
      diese Rolle übernimmt.
- 23 Pläne und **28** Spezifikationen unter
  [`docs/.superpowers/`](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers),
  dazu **zwei** SDD-Verzeichnisse — `2026-08-28-installer-kern/` mit einem
  `crlf-fix-report.md` und seit 2026-09-10 `2026-09-07-worktree-mirror/` mit
  dem Ledger. Beide ungetrackt, `.gitignore:2` ignoriert `sdd/` als
  Arbeitsspur. Nach `AGENTS.md` sind Pläne und Specs Arbeitspapiere: einmal
  geschrieben, von einem Menschen gelesen, nie übersetzt.
