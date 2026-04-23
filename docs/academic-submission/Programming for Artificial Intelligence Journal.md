# Programming for Artificial Intelligence Journal

Preface: I’m a PI in the project. This is something that I wish to do for my PhD, and I’ve done 80% of the work. It is understandable: I’ve spent the last 7-8 weeks \+ previous experience attempting this exact project a year ago. Because it was more complex, when I invited people to my project, we both agreed I would carry out most of the work.

### June 2024-April 2025

I’ve done this exact project -- well, an attempt at solving this exact problems a year ago. When I started, I knew nothing about ML, so I started learning and spent months trying to figure out how to solve this -- I wanted to solve a problem and start a big company in the space.I have written software at evenings at weekends for 3 months, then it took me about 6-8 months on learning machine learning basics, at which point I decided that I no longer should support the project

### January 29th -- project reinitiated

I’ve taken my old code (there wasn’t much) and refactored it using AI. AI introduced some awful abstractions; so bad that I’ve spent 2-3 days trying to refactor it to a proper state, at which point I’ve dropped the codebase and re-started from scratch.

### February 7th -- starting to write specifications

Reflecting on my failure, I’ve spent 3 full-time days writing specifications -- on what is expected from the application and exactly how it should work, the rules of the code (note: see .agents/skills for all the rules), to the point where there was approximately 3.5 thousands of lines of markdown by days 3\.

I’ve explicitly didn’t write specifications using AI during those days. Explicitly, everything must have worked.

Important rules for project code:

1. All code is strongly and explicitly typed -- dicts are banned, everything must work using enums, Pydantic models everywhere.  
- This was clearly a good decision. At this point my environment has over 345 classes. If any of this would be omitted, migrations would be incredibly painful.  
- Which they were during early days, hence the rule introduced  
2. Rules for writing specifications were introduced

#### Architectural decisions made early:

- The system had to improve over time, and Generic Pareto optimization (also known as the engine behind DSPy), was introduced to improve prompts as a reinforcement learning process  
- The system had to scale -- I made distributed LLM controller and worker nodes. Meaning, simulation and   
- Simulation using MuJoCo and Genesis-World (the most capable simulation engine to date, while staying fast), support for electronics, deformable materials is first-class  
- Black-box integration testing -- tests are disallowed to import anything from the system or mock anything. (see @specs/[integration-test-rules.md](http://integration-test-rules.md)) Hence, the tests can only query the system using HTTP requests, which, while creates slow tests, creates much stronger test coverage -- we *always* know that a system will respond in a given way. “Unit tests” are disallowed.  
- Explicit list of integration test -- we have a list of integration tests, (which at some point was) 270+ integratio tests strong (later pruned 70% because it has become unmaintainable)  
- Frontend application as a debugging tool.  
- Multi-agent system -- I don’t expect a single agent to handle engineering or test creation. Plus, for data generation, planners, implementers, reviewers are desired.

### February 10th -- implementation kickoff.

After dropping the codebase, I’ve reimplemented what was already there in 1-2 days, except this time with more or less proper code and ownership.  
With tests doing HTTP boundary, I was more or less confident it would work.

My architectural choice -- I’ve heard that agents using LangChain or DSPy are the best, so 10-13th Feb was spent implementing LangChain agents. Which took a lot of work, because I wanted to make the application reliable -- if something in the pipeline breaks, ***even silently***, it would take the whole run down\!

### February 13th -- I had nothing to do, so…

While I was waiting for the implementation, I had nothing to do and started implementing support for:

* Fluids,  
* Electronics,  
* Deformable bodies

Yes, I still haven’t ran a single successful experiment, but hey -- AI can code, which means that I can just write a few prompts and the application will work\!

Right? 

Well, with that, my integration test coverage needed to be doubled, my integration tests became slow because supporting deformable bodies requires simulators that compile twice as long (full-featured Genesis-world vs lighter, zero-compilation MuJoCo)

It was a terrible decision. It has bloated my codebase, focused me off doing the most important work, and in the end, I have spun wheels debugging all that mess -- introduced *because I had nothing to do* in just in one evening -- for the next two weeks. Note: in my term when I say a “week” I say: 7 days a week, with me waking up at 5am and going to 9am, the rest is coding. Yes, I work 80-100 hour workweeks regularly.

(735 commits in the window between February 15th and March 3rd)

**As summarized by a coding agent:**  
  *- Feature implementation*  
      *- Steerability and design-feedback work packages.*  
      *- Fluids, Genesis/physics, and electromechanical integration.*  
      *- Electronics simulation, validation, and visualization.*  
      *- Benchmark planner and benchmark-generation updates.*  
  *- Agent/runtime refactors*  
      *- Transitioning agent nodes to DSPy/ReAct and then hardening that runtime.*  
      *- Pydantic/typed schema propagation across controller, worker, and shared models.*  
      *- Handover validation, filesystem policy tightening, and permission updates.*  
  *- Simulation and worker stability*  
      *- Genesis backend improvements, performance tuning, and crash containment.*  
      *- Heavy-worker / light-worker split and concurrency fixes.*  
      *- Session tracing, observability, and error-log handling.*  
  *- Integration-test hardening*  
      *- A lot of test fixes for P0/P1 flows, mock scenarios, backend routing, and frontend stability.*  
      *- Review/gate behavior, error allowlists, and deterministic session handling.*  
  *- March 1-3 specifically*  
      *- Code review cleanup, structured metadata/trace changes, backend log detection, and stricter error policies.*

### March 10th -- “I thought I’d implement this in two weeks?”

The integration tests got stable -- about 200 tests were passing green in the codebase.  
This is where I started running agents.

Agents weren’t able to solve a single problem successfully. Even the simplest ones.   
The issue was -- too much instability in the codebase. Integration tests were passing, however the logic was flaky and was failing agents on every turn. Bugs were slow -- too slow to debug.  
I don’t have a nVidia GPU, so I can’t run these models locally. And even if I had, say, a RTX4090 -- there is no point -- small models can barely code, and solving engineering problems? I doubt it.

No agents passing.  
I’m burning a bit of money on agents’ in the cloud -- something like 60 EUR spent in a week time -- and I wasn’t intensive -- I’ve barely run anything

### March 17th -- I’m debugging the application

Let me be clear: the codebase is 60k SLOC, at that point of time without tests or clutter. (now it’s about 80k)

And the application crashed, fails silently, and anything under the sun. It requires human evaluation. 

At this point, the specifications themselves are are 7-8K lines of markdown, and growing (at this moment, it’s 10k, 100k+ words. (Harry Potter and the Philosopher's Stone is \~77K)

Specs are effective though, because my agents do what I want.

### March 24th-31st -- “I thought I’d implement this in two weeks?” *(and it’s been two months?)*

Debugging frontend, speeding up integration tests (turns out, I had genuinely stupid HTTP chatter, forcing 46 unnecessary, serialized HTTP requests that even on localhost took \+10 seconds)  
Integration tests are now faster. The agents still can’t solve the task. It’s too much to scale from here too.

I still kept introducing and pruning logic  
Let me make a point, by the way -- my github screenshot:  
![][image1]	  
Those “light green” days are 30 commits/day commits. Yes, I code 7 days a week, in attempt to make myself a better life, I guess.

### March 30 -- “I thought I’d implement this in two weeks?” *(and it’s been two months?)*

I’m starting to get seriously anxious. My assignments are due, and I hadn’t been able to produce anything successful yet. But the application doesn’t work\! Issues pile up here and there.  
At this point, I started contemplating reducing the application back to the very basic state -- remove the frontend, deformable bodies, electronics, motors, fluids, off-the-shelf-price, manufacturability -- and leave only rigid-body simulation.  
Well, debugging is the way forward.

And I did debug some of that logic. But what’s the point if agent don’t work?  
I’m intensively reading papers on ideas on how this can be solved.

### March 31-April 7th -- debugging and agent work.

I’ve decided to make better rendering in hopes that it would improve whether agent can or can not simulate properly (again, had nothing to do?) which as it turned out was a bad decision because for some reason, that rendering segfaulted on my machine without additional warning.  
As it turned out, because I’m on Ubuntu 24, which has Wayland and not X11 rendering, rendering via standard X11 methods was impossible. I’ve burnt three days on just figuring out that the solution would be to introduce another docker container which wouldn’t be constrained by Wayland.

I’ve also taken significant implementation changes on how the planning works. In particular, engineer\_planner agents now have to draw a map on exactly how they expect a payload to move during the simulation, the trajectory must align to a subsecond measure. If the payload deviates or moves too slowly or too fast by the trajectory, the episode now terminates early.

***This has exposed a lot of bad planning.*** Agents have consistently come up with payload trajectories which routed through areas which have intersection. I really made sure that collision detection with payload is explicit.

### April 8th to 15th -- I’ve had enough of feature bloat

While making many things more and more robust, I decided that this is enough, I want to publish the paper, and -- because I’ve seen agents failing to work already, adding more features would not make sense.

I’ve spent two days pruning:

* Fluids,   
* Motors  
* Electronics  
* Off-the-shelf (imported) components, e.g. bearings and fasteners)  
* Anything except gravity-induced benchmarks

It went fairly quickly in project length, and after it was done.

The result? The agents still couldn’t even make plans on how physics will work. Let alone solve the problem.

This is the reality I’ve been going after for two months -- even strong agents agents can’t. And custom models are necessary if I want to make any impact.

### April 15th to 22nd -- getting a small subset of features to work

Even though my codebase has 80k lines of code and fairly extensive test coverage, it could barely perform.  
engineer\_planner succeeded with 20% success rate (note: hard planning constraints imposed), and oftentimes because of strange “luck” rather than because of real model capability.

I know that I need to do GRPO and am actively researching what I need to do to do it on this RL task. I know that if I want to do reinforcement learning and fine-tuning, I will also want to do pre-training first, because it allows for very substantial gains, and both require substantial compute.

I’m trying to start a few projects in attempts to make my submission more credible. An algorithm to translate one CAD framework to another -- I’m using the latter, however agents are not as capable in it as it’s significantly less popular in training corpora (even though recognized as more convenient for modelling).

The remainder days are spent… Getting anything to be publishable. Pushing to the deadline.

I know that at least the dataset for solving problems is ready.

### April 23rd -- creating the dataset

The dataset was created over one day -- it was hand-verified; and it’s a relatively quality dataset; with that, it’s only 100 entries; even though anybody with compute resources could readily do tens of thousands.

And that’s about it.

Feature bloat got in my way a lot during this application development, and I believe I still want to do my PhD on the topic, or become a researcher in a company; best start my own company. With that, its a field nobody has advanced in before, and taking steps is rather challenging because it’s easy to assume that agents, which are so incredibly good at code, would be equally good at writing geometrical code. Turns out, they struggle, though in dataset generation, and reduced feature set, they can perform complex operation.
