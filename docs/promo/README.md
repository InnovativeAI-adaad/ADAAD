# ADAAD Promotion Kit — Master Index

> **All promotion assets are ready to post. No editing required, though personalisation improves results.**
> Assembled by ArchitectAgent — 2026-03-07

---

## Assets in this directory

| File | Channel | Status |
|:---|:---|:---:|
| `HACKERNEWS_SHOW_HN.md` | Hacker News — Show HN | ✅ Ready |
| `PRODUCT_HUNT_LAUNCH_KIT.md` | Product Hunt | ✅ Ready |
| `TWITTER_THREAD.md` | Twitter / X | ✅ Ready |
| `REDDIT_POSTS.md` | r/programming, r/MachineLearning, relevant governance and AI safety communities, r/devops, r/androiddev | ✅ Ready |
| `NEWSLETTER_OUTREACH.md` | TLDR, Console.dev, Changelog, Dev.to, GitHub Blog | ✅ Ready |
| `DEVTO_BLOG_POST.md` | dev.to / Hashnode (full post) | ✅ Ready |

**Marketing site:** deployed at `gh-pages` branch → `https://innovativeai-adaad.github.io/ADAAD/`

---

## Recommended launch sequence

### Day -7 (one week before)
- [ ] Email newsletter editors (NEWSLETTER_OUTREACH.md)
- [ ] DM a Product Hunt hunter with 10k+ DevTools audience
- [ ] Submit dev.to blog post (DEVTO_BLOG_POST.md) — set to publish on launch day

### Day -1
- [ ] Confirm Product Hunt hunter is lined up
- [ ] Queue Twitter thread (TWITTER_THREAD.md) to post at 9am launch day
- [ ] Alert your personal network (Slack, Discord, email) — ask them to be ready to upvote

### Launch day
- [ ] **9am ET:** Product Hunt goes live (coordinate with hunter)
- [ ] **9am ET:** Twitter thread posts (Tweet 1 through Tweet 10)
- [ ] **10am ET:** Hacker News Show HN submission (HACKERNEWS_SHOW_HN.md)
- [ ] **10am ET:** r/programming post (REDDIT_POSTS.md)
- [ ] **11am:** Reply to every HN comment within the hour
- [ ] **Noon:** dev.to blog post publishes
- [ ] **2pm:** r/MachineLearning post
- [ ] **End of day:** relevant governance and AI safety communities + r/devops posts

### Day +1
- [ ] r/androiddev post
- [ ] Follow up with any newsletter editors who expressed interest
- [ ] Respond to all outstanding Reddit/HN comments

---

## Core URLs (use consistently across all channels)

| Asset | URL |
|:---|:---|
| GitHub | https://github.com/InnovativeAI-adaad/ADAAD |
| Marketing site | https://innovativeai-adaad.github.io/ADAAD/ |
| Quick start | https://github.com/InnovativeAI-adaad/ADAAD#-start-in-60-seconds |
| Constitution | https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md |
| Plain English overview | https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/ADAAD_PLAIN_ENGLISH_OVERVIEW.md |
| Android install | https://innovativeai-adaad.github.io/ADAAD/install |
| Releases | https://github.com/InnovativeAI-adaad/ADAAD/releases/latest |

---


## QR attribution conventions

- QR assets are registry-driven: `docs/assets/qr/registry.json` is the source of truth.
- Every active QR target must use one of two attribution-safe patterns:
  1. Approved UTM query params (`utm_source`, `utm_medium`, `utm_campaign`), or
  2. A managed redirect endpoint under an approved prefix.
- Current campaign convention: `utm_source=qr` and `utm_campaign=install_tracks_2026q2`.
- `utm_medium` is **placement-specific** (for example `install_card`, `install_android_doc`, `readme_banner`) so scans are attributable by channel/surface.
- Never reuse one QR asset across placements; generate one asset per placement in the registry.
- Validate before publishing: `python scripts/validate_qr_registry.py`.

## Key messages (keep consistent across all channels)

1. **Lead:** "AI that improves your code — but can't approve its own changes"
2. **Differentiator:** Constitutional governance is architecturally enforced, not just documented
3. **Trust signal:** Deterministic replay — every decision byte-identically reproducible
4. **Phase 6 hook:** The engine proposes changes to its own roadmap. Humans approve.
5. **Access:** Governed proprietary access, proprietary license, Android app with no Play Store required

---

## Audiences that will resonate most

- Teams in regulated industries (fintech, healthcare, legal tech) where auditability is a requirement
- Security engineers who've had to justify AI-generated code to a compliance team
- DevOps engineers who deal with change management and audit trails
- AI safety researchers interested in practical governance implementations
- Open source developers interested in governance-first architecture
- Android developers interested in zero-cost distribution strategies

---

## Common questions and answers (for comments/replies)

**Q: Is this just another AI coding assistant?**
A: The key difference is the governance layer. AI assistants suggest changes and let you decide. ADAAD runs a formal constitutional gate before anything is applied, produces a cryptographic evidence bundle for every decision, and makes every decision deterministically replayable. The AI cannot approve its own changes.

**Q: Why three agents instead of one?**
A: Diversity in proposals, same governance gate. Architect tends toward safe, methodical changes. Dream tends toward creative restructuring. Beast pushes complexity limits. They compete — the genetic algorithm picks the fittest. A single agent monoculture produces less interesting candidates.

**Q: What does "deterministic replay" actually mean?**
A: Given the same inputs, the governance pipeline produces byte-identical output. Any past governance decision can be re-run and will produce the exact same verdict. If a replay ever diverges from the original, the pipeline halts immediately. This makes auditing real, not theoretical.

**Q: How is the constitution enforced?**
A: `GovernanceGate` evaluates the versioned constitutional rule set in order (see Constitution + governance artifact for current count). Any BLOCKING rule failure immediately rejects the mutation and logs the failure. There is no way to bypass this — it's not a config flag, it's the only path mutations travel through.

**Q: Can the AI modify its own constitution?**
A: No. The AI can propose a constitutional amendment, but it must pass through the same GovernanceGate as any other change, requires Tier 0 classification (highest oversight), and requires explicit human sign-off before it takes effect.

**Q: What LLM does it use?**
A: Claude (Anthropic API). You bring your own API key. The system is designed around the Claude API but the proposer interface could theoretically be adapted.

**Q: Is the Android app really free?**
A: Yes. proprietary license. No Play Store account required. Four install tracks: direct APK from GitHub Releases, Obtainium auto-update, PWA (Chrome), and F-Droid.
