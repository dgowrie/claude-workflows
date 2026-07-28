---
name: grilling
user-invocable: true
description: >
  Grill the user relentlessly about a plan, decision, or idea, walking the decision tree
  branch by branch and recommending an answer for each. Use when another skill needs a
  decision-tree grilling loop, or when the user wants to stress-test their thinking. This is
  Matt Pocock's variant; for the customized version see /grill-me.
---

<!-- Based on https://github.com/mattpocock/skills/tree/main/skills/productivity/grilling -->
<!-- Kept as a distinct skill from the customized /grill-me so improve-codebase-architecture and codebase-design can call it by name without clobbering the local customization. -->

# Grilling

Interview me relentlessly about every aspect of this until we reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the environment (filesystem, tools, etc.), look it up rather than asking me. The *decisions*, though, are mine; put each one to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.
