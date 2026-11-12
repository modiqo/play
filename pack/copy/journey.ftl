# Play's wording for rote prompts. Each id replaces rote's baseline message
# of the same id (crates/rote-guidance/baseline/copy/journey.ftl in rote).
# An attribute left out here keeps rote's text. Ids rote does not define
# fail lint.

prompt-near-match-offer = These Plays come close, but none matches exactly. Which one should I inspect before asking whether to run it?

prompt-approve-run = Run this Play with the parameters and effects shown?
choice-approve-run-cancel = Not now
    .description = Stop without installing, replacing, authenticating, or running anything.

prompt-sign-in = Sign in to rote to continue this Play request. Which sign-in do you want?
choice-sign-in-google = Continue with Google
choice-sign-in-github = Continue with GitHub
choice-sign-in-cancel = Not now
    .description = Stop without signing in.

choice-route-recovery-retry = Try another tool
choice-route-recovery-stop = Stop exploration
    .description = Keep the evidence recorded so far, and save or publish no Play.

prompt-save-offer = How should I keep this verified exploration as a Play?
choice-save-offer-team = Team
choice-save-offer-community = Community
