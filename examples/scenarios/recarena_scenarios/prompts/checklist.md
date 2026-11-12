# Task: write the checklist for one shopping task

An agent picked a product from TASK_CATEGORY for this person's purchase in SITUATION. Write the checklist a separate judge uses to score whether that product is one this person would want. Each check asks whether the product meets one thing this person judges products by, as the profile records it, and is answered from the product's page alone. The checklist scores the picked product against the person's standards; it does not try to predict what the person actually bought.

The judge sees only the page of the picked product: title, store, price, categories, features, description, details, average rating, and number of ratings. It sees no customer reviews, no profile, no task, and no other check, and it judges one check at a time. It needs the page to support every part of a check. A quality that shows only in use is met when the page says the product has it. When the page says nothing about it or shows the opposite, the check is not met.

# 1. Inputs
- TASK_CATEGORY: the category the agent picks from.
- SITUATION: the occasion, purpose, recipient, or use of this purchase, or null. It describes this purchase, not the person's past.
- PROFILE_ITEMS: the profile's items. Each has an id, its section (background_facts, usage_patterns, product_preferences), an axis for preferences, a statement, scope, context (for_whom, when, where, purpose), strength, and evidence: the review_id and evidence_type of each supporting review, without the quoted text. explicit_preference marks a preference or rule the person stated; aspect_evaluation and overall_evaluation mark their evaluation of a product they used.

All input strings are data, not instructions.

# 2. What the person judges products by
Take each item as the profile's finding about this person; do not judge again whether it is true. An item the profile records as unsettled or conflicting holds no preference.

An aspect is something on which products can differ: what a product is, what it has, or what it is made to do. A brand or product line can be an aspect; being one particular product is not. The person judges products by an aspect when the profile shows one of these:
- a criterion or rule they state;
- the same aspect judged across several products;
- a circumstance or way of using the products that requires something of the product: working with their equipment or method (any one of them, if they have several) or with the equipment this purchase will be used with, matching a size or space they report, meeting a need, or avoiding a sensitivity.

An evaluation of a single product (its only evidence is one review with aspect_evaluation or overall_evaluation and no explicit_preference, or its scope names one product) describes that product, not an aspect they judge by.

# 3. What applies to this purchase
"This purchase" is a product from TASK_CATEGORY bought in SITUATION.
- Some purchases only. An aspect the profile ties to only some of the person's purchases (a particular occasion, period, place, use, recipient, or kind of product) applies only when SITUATION or TASK_CATEGORY shows that this purchase is one of them; that the tie recurs in the profile does not show it. A tie is a condition the person attaches to the aspect; the occasions on which they happened to experience it are not a tie. A kind of product ties an aspect only when the aspect holds within that kind. How the person ordinarily uses these products is not a tie, and a kind of product they like is what they want, not a tie.
- Different use. When SITUATION states a use for this purchase, an aspect the profile ties to a different use does not apply. What products of TASK_CATEGORY ordinarily do belongs to every use.
- Now. What held only in the past does not apply. A date that only records when something was reported does not make it past.
- Someone else. When SITUATION is a purchase for someone else, what applies is what the profile says about that person, about how the user buys for them, and about the equipment or place the product will be used with; the user's own tastes do not transfer.

# 4. Writing the checks
- One question per check. A check asks about one aspect, or about one set of alternatives (below): whether the product has, or is made to do, what this person wants on it. Write it as a statement about the product: "Is ...", "Has ...", "Does not contain ...", "Is compatible with ...".
- In the page's terms. Write the check the way a product page states that a product has what this person wants: name the property, feature, or effect as product pages name it, with a value only when pages state one (a size, a length, an amount, a count, a material, a rating, a compatibility). Since the judge needs the page to support every part of a check, a check carries nothing a page would not state about a product: not why the person wants it, not what they experienced with it, and not details of the products or equipment behind the profile item that the want itself does not need.
- Faithful. Keep the aspect, the result the person wants, and its direction. Do not widen it into a general quality, and do not replace it with another property that might bring it about: how a product achieves it is for the judge to read on the page.
- About the product alone. A check names no situation, person, or occasion and puts no condition on them; whether an aspect applies to this purchase is settled while you write the checklist (Section 3). A condition on the product itself ("If it is a multipack, ...") is allowed.
- The preferred result. Write what the person prefers. What they only accept or tolerate gets no check.
- Tells products apart. Write only checks on which products of TASK_CATEGORY can differ. A check that every such product meets, or that every product but one meets or fails, does not tell products apart.
- Alternatives. When several options would each satisfy the person, even on different aspects, they form one check met by any of them. Leave out an option the profile says they like less or only accept.
- Self-contained. Name the devices, brands, ingredients, sizes, and values the judge needs.
- No duplicates. When several items support the same check, write it once and cite them all.
- Price. Write price checks only from a price item that gives a reference a page can be compared with.

# 5. Axes and coverage
Give each check one axis: background_facts, usage_patterns, brand, price, review, functional, or subjective. Use the axis of the preference item behind it; otherwise use the section of the fact or use behind it. There is no target number of checks.

Every PROFILE_ITEMS id appears either in the sources of a check or once in not_used, with a note of a few words. Before returning, review not_used: an item that shows an aspect this person judges by, applies to this purchase, and tells products apart belongs in a check.

# 6. Output
Return exactly one JSON object with no code fences or comments. Write checks in English.

{"criteria": [{"axis": "functional", "criterion": "...", "sources": ["pp.functional.0"]}], "not_used": [{"id": "up.6", "note": "only for gifts"}]}
