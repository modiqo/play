# 🏆 THE PLAYOFFS

### 100 builders. One shared arena. The best Plays win.

You know that thing you do every week that takes eleven steps, three tabs, and one small prayer?
Someone in this hackathon is about to turn it into a one-liner. It might as well be you.

**The Playoffs** is a hackathon for people who are tired of doing the same brilliant thing twice.
You'll install [rote](https://github.com/modiqo/rote), teach it something only you know how to do,
and publish it as a **Play** — a reusable, inspectable, runnable procedure with a birth
certificate and your name on it. Then 99 other people get to run it. Live. The moment you ship it.

---

## 🎟️ The rules (there are barely any)

1. **Everyone ships.** All 100 participants create **at least one Play**. More is better.
   Masters don't stop at one.
2. **One arena.** Every Play is published to the shared **`hackathon`** space. That's the court.
   Everything published there is visible to every participant.
3. **Instant scrimmage.** The moment your Play is published, everyone else can see it in their
   Play inbox (`$play whats new`) and **run it live** — inspected first, approved, then executed
   for real. No demos, no slideware. If it doesn't run, it doesn't count.
4. **Build for the habit.** The goal is not a party trick. The goal is a Play so useful that a
   stranger runs it once, then runs it every day without thinking. The best Plays become muscle
   memory.

## 🥇 The prizes

Three Plays will be crowned **Masters**. Their creators take home:

| Place | Prize |
|---|---|
| 🥇 **First** | A MacBook. Yes, really. |
| 🥈 **Second** | The [Work Louder Creator Micro 2](https://worklouder.cc/creator-micro-2) — a keypad worthy of your new one-keystroke workflows |
| 🥉 **Third** | More good stuff (announced at kickoff) |

And every participant walks away with the real prize: a personal arsenal of 100 Plays built by
100 people who automated the annoying parts of their week. You will steal each other's best moves.
That's the point.

## 🧑‍⚖️ How we judge

The judges score every published Play on four things:

- **Daily-habit gravity** — would a reasonable person run this weekly? Daily? Reflexively?
- **It actually runs** — pulled fresh, inspected, executed live from the `hackathon` space by
  someone who is not you. Verified output, not vibes.
- **Reusability** — clean parameters, honest descriptions, stable output. A Play a stranger can
  trust after one read-only inspection.
- **Adoption** — the scoreboard doesn't lie. Downloads and installs by your fellow competitors
  count. If half the arena runs your Play by finals, that says something no pitch deck can.

## 🚀 Getting on the court

**1. Suit up (10 minutes).** Install rote and sign in — the guided setup holds your hand:

```bash
curl -fsSL https://rote.modiqo.ai/install.sh | sh
rote login
```

Then install Play, your sidekick for the whole tournament:

```bash
claude plugin marketplace add modiqo/play      # or: codex plugin marketplace add modiqo/play
claude plugin install play@play-skills
```

Type `$play` and run **Hello** — public data, no credentials, no writes. That's your first rep.

**2. Join the arena.** Accept your invite to the **`hackathon`** org. From then on,
`$play whats new` is your scoreboard: every Play published to the space, grouped and ranked,
fresh in your inbox.

**3. Find your Play.** The best Plays come from your own annoyances. Do your work normally —
check a PR, pull a report, triage an outage, chase DNS, reconcile invoices. When you finish
something you know you'll do again, tell your agent:

```text
$play settle checked deploy status and posted the summary
```

Play will judge whether it's worth saving — and if it is, walk you from working memory to
published Play: crystallize, release, publish to `hackathon`, birth certificate and all.

**4. Ship early, ship loud.** A Play published on day one gets a week of adoption. A Play
published an hour before judging gets a participation ribbon. You do the math.

**5. Run everyone else's Plays.** Seriously. It's how you win *and* how they win. Every run is
adoption signal for them and a stolen superpower for you.

## 📅 The season

| Date | What happens |
|---|---|
| **TBD** | Kickoff — invites go out, the `hackathon` space opens, Hello runs everywhere |
| **TBD** | Mid-season check-in — the inbox leaderboard goes up on the big screen |
| **TBD** | Publishing deadline — the arena locks |
| **TBD** | Live finals — judges pull, inspect, and run the finalists in front of everyone |
| **TBD** | The Masters are crowned 🏆 |

## 📣 Fine print, minus the fine

- Plays must run through `rote play run` from the shared space — that's what "published" means.
  Every Play carries a birth certificate; provenance is part of the craft.
- Credentials stay yours. Plays declare what they need by *name*; they never carry secrets.
  Anything with write effects discloses them before anyone approves a run.
- Teams welcome, but prizes are per Play — figure out who gets the MacBook *before* you win it.
- Judges' Plays are exhibition only. They want your keyboard prize as much as you do, which is
  why they can't have it.

---

### One more thing

Six months from now, nobody will remember the hackathon that produced a clever demo. Everybody
remembers the Play they still run every morning. Build *that* one.

**See you in the Playoffs.** 🎬

*Questions? Ping us in the hackathon channel, or just type `$play` and ask.*
