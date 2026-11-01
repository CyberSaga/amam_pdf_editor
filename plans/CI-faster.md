owen

@owengretzinger
How I made our CI 20x faster (steal this)
A year ago, a PR at Boardy waited up to 40 minutes for CI. Now it waits 2. That matters more than ever, because every PR we ship is written with coding agents, and agents don't get tired of pushing. They push, wait for CI, fix the red check, push again. When writing code gets 10x faster and CI doesn't, CI is what you're waiting on.
Arpit Bhayani
@arpit_bhayani
·
10月23日
If AI makes you 10x faster at coding, why is your team not shipping 10x faster? Amdahl's law has the answer...

The law says the overall speedup is capped by the part you did not speed up. With `p` as the fraction of the work you accelerate and `s` as the speedup on that
顯示更多
So this month I treated CI like a product, doing most of the work using an internal agent in Slack from my phone.
Give this article to your agent and have it do the same to yours.
Change
Before
After
Runners that aren't GitHub's
up to 11 min waiting for a machine
8 seconds
Oxlint instead of ESLint
2 minutes
5 seconds
tsc to TypeScript 7 to bun check
70 seconds
under 5
Test files share a worker
100 seconds per shard
35
Cache seeded from main
half of PR runs missed
1%
1. Get off GitHub's default runners
Our jobs waited up to 11 minutes on GitHub's hosted runners just to get a machine. Now they start in 8 seconds. It's one line per job:
yaml
runs-on: blacksmith-4vcpu-ubuntu-2204
We use Blacksmith. There are also a bunch of other great options launching like Vercel CI, boat.dev, and a dozen more. Any of them beats the default.
Vercel
@vercel
·
10月29日
Introducing Vercel CI

• Intelligently skips tasks with Turborepo
• 2-6× faster CI in our internal repositories
• Optimized for agents via Vercel MCP and CLI

After nearly 8 million tasks, we're excited for the future of agentic CI. In beta on all plans.
顯示更多
來自 vercel.com
Move every job, including the tiny ones. We left our two smallest on GitHub because they only run for a few seconds, and they became the slowest part of the pipeline. A 5-second job that waits 10 minutes for a machine is a 10-minute job.
Runners got us from 40 minutes to about 10. Everything below is the rest.
2. Replace ESLint with Oxlint
Lint went from 2 minutes to 5 seconds.
Agents don't get annoyed by strict rules, so turn on everything you can. Enforce the "black hole of success".
Matt Pocock
@mattpocockuk
·
10月28日
We used to talk about a "pit of success".

Humans would be dragged towards writing the right code by well-designed API's, a good test suite, sensible lint rules.

You couldn't make the pit too steep, otherwise the humans would get annoyed. There was a social contract.

Feels like
顯示更多
3. Switch typecheckers every time a faster one ships
We switched our typechecker three times in a month.
Our server's cold typecheck was 70 seconds on tsc. TypeScript 7 took it to 13. bun check does it in under 5, so that's what CI runs. Locally, tsrs does it in 0.6 seconds.
I was at a dinner when Jarred posted that bun check was getting up to 7x faster. So I pasted the post into an internal Slack agent. Six minutes later it had benchmarks from our repo. Twenty minutes after that the PR was merged.
Jarred Sumner

@jarredsumner
·
10月19日
In the next version of Bun

bun check gets 1.7x - 7x faster
4. Shard your tests onto bigger machines
We split one 8-minute test target into six shards on 8-vCPU machines, each with its own database.
Bigger machines mattered more than more shards. Each shard spent most of its CPU loading modules and almost none of it running tests, so we bought cores, not shards.
5. Stop reloading your app for every test file
Vitest gives every test file a fresh worker, so every file imported our whole NestJS app from scratch. Set isolate: false. Each of our shards went from 100 seconds to 35. Linear found the same thing:
來自 linear.app
Tests will start leaking into each other. Add a hook that resets state after every file, and tell your agents what a test has to clean up.
6. Fix setup
Last week our server test job took 168 seconds. Now it takes 74. The tests inside it barely changed. Almost all of that came from setup, which is the part nobody looks at (and agents missed initially).
The biggest piece came from an audit. I asked an agent to pull our last 150 runs and split every job into waiting, setup and running. It found that half our test jobs were missing the dependency cache. GitHub scopes PR caches to their own branch, and nothing seeded one from main, so most PRs started cold. That bug had been there all year. Nobody noticed because nobody was sitting there watching CI. The agents were, and they just retried instead of fixing the actual issue.
Andreas Kling

@awesomekling
·
8月19日
>code is slow
>ask agent if it’s one big bottleneck or death by a thousand cuts
>it doesn’t understand
>pull out illustrated diagram explaining one big bottleneck vs death by a thousand cuts
>it laughs and says “it’s one big bottleneck sir”
>look at profile myself
>it’s death by
顯示更多
Three more:
Cache node_modules. Ours restores in 13 seconds and replaces a 33-second install.
Use a blobless clone, filter: blob:none, not a shallow one. Shallow breaks anything that reads git history. Checkout went from 36 seconds to 12.
Match parallelism to your cores. Our 4-vCPU job was running 8 tasks at once. Halving the concurrency was just as fast and killed a flaky test.
I also tried deleting tests. An agent audited all 20,000 test cases in our server and found almost nothing worth cutting, and the time was never in the tests anyway.
Peter Steinberger 🦞

@steipete
·
9月24日
OpenClaw deleted around 400k LOC of its own tests without much change in code coverage. Modern models just love writing tests for every tiny change, even if they aren't useful. This skill helped.
來自 github.com
7. Run everything in parallel
Lint, typecheck, build and tests all run at once. A PR takes as long as the slowest one.
Then look at what else your slowest job is doing. Our first test shard was also running migration checks and other apps' tests, so it always finished last. Moving those into their own job cut 2 minutes.
8. Only run what a PR touches
Kun Chen
@kunchenguid
·
10月29日
now that we all agreed to not review most of the code any more, CI became the next bottleneck

at agent speed, if our CI pipeline is simply "run all the build, lint, tests", it'll become a major slow down

here are a few things i suggest for how to optimize:

1. balance load
顯示更多
We use nx affected so a PR only tests the projects it changed, and run the full suite every night on main.
Then test the skip logic itself. We hid a server change from Nx on purpose and all six shards skipped their tests and reported green. Now that fails the run.
9. Run the checks before every push
Our pre-push hook runs format, lint and typecheck on changed files in under 9 seconds. An agent that hits a type error locally fixes it in seconds instead of waiting for CI.
Put it in a hook rather than a line in AGENTS.md, because agents skip steps.
Rory Graman

@rorygraman
·
10月24日
回覆 
@0xKoller
just set up a hook on pre-commit to run typecheck and lint. agents MUST follow that. long sessions leave agents passing up CLAUDE.md/AGENTS.md most of the time.
What it costs
Our CI bill went from $230 a month to $4,300, but it's the cheapest money we spend on making agents faster.
Flo Crivello

@Altimor
·
9月27日
CI has become the top bottleneck of every engineering team I talk to (including Lindy). Our CI spend has become stratospheric.
引用
David Ondrej
@DavidOndrej1
·
9月27日
my GitHub Actions spend is going out of control
What's next
Now that agents write the code and CI only takes 2 minutes, the slowest part of the loop is me clicking merge. With dozens of agent sessions going at once, sometimes it still takes a while for me to get work across the finish line.
So it's time to address the next biggest bottleneck: me.
