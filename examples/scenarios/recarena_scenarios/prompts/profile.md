# Task: describe one user's shopping preferences
Read the provided reviews by one user in one product category and write one reference document about this person using the supplied JSON Schema.

# 1. Goal
Describe what this person wants, avoids, needs, and does when choosing and using products in this category, generalized across the whole history:
- the circumstances that shape their choices (background_facts),
- how they buy and use the products (usage_patterns),
- the criteria they choose by (product_preferences).

Generalize how far a statement reaches, but keep what it says concrete.
- The reach (scope) grows from one product to the product type when the evidence shows a criterion rather than a single evaluation (Section 2).
- The content stays at the aspect the person actually judged and the result they want, in their terms.
"Wants headphones whose battery lasts a long day" is a generalization. "Values quality" is an abstraction: it names nothing a shopper could check, so it is not a usable preference.

# 2. Principles
1. Grounding. Every claim about the person comes from their own review titles and texts.
   - Product metadata, ratings, dates, and what the reviewed products have in common identify what a statement refers to and put statements in order. They are never the content of a claim about the person, and what the reviewed products have in common never sets its scope. When the review text and the metadata disagree about which product or variant is meant, follow the review text.
   - Read each statement for what it asserts. A description of a product, a suggestion of what it would suit ("great for camping"), advice to readers, a joke, or a hypothetical does not report the person's own use, situation, or criterion.
2. Proportion. How far a claim reaches depends on the kind of evidence, not on how many times it appears.
   - A general rule the person states about their own choices ("I never buy pans with a nonstick coating"), or a choice they say they made because of an aspect (switching brands over leaks), supports a general item even if it appears once.
   - Evaluations of the same aspect across several products, favorable or not, show a criterion the person chooses by. Write the criterion once, with the product-level results as its evidence.
   - A single evaluation of one product's feature stays at that product's scope. Attach it as evidence to a criterion it illustrates, or keep it as a narrow item when no criterion fits.
   - A claim must hold for all of its evidence. When a counterexample, an accepted compromise, a condition under which the person chooses otherwise (such as a lower price), or a change over time appears, state it in the item instead of smoothing it away. Conflicting statements with no stated reason stay as a conflict with both sources.
3. Attribution. Keep who, when, and under what condition straight.
   - Separate the person from others they buy for or mention; a relative's taste is the relative's, and a purchase for someone else names that recipient.
   - Keep conditions the person attaches to an attitude ("for camping, I pick ones that pack small").
   - Separate what held only for a past period from what is ongoing. Wording that only dates a report ("at the time") does not by itself make a circumstance past; judge from its content.
   - Use "the user" or singular "they". Do not infer gender, age, health, residence, or other attributes the text does not state. A generic "you" describing an experience is the writer's own experience; "we" reports the writer together with others; advice to readers concerns no particular person.

# 3. Sections
Use exactly these top-level fields: background_facts, usage_patterns, product_preferences.

## background_facts
Facts the person states about their circumstances, each with fact and evidence; the sentence says whose fact it is.
- equipment: tools and devices used with the products, including limitations.
- environment: facilities, space, surroundings, or local services that affect use or choice.
- people: stated relationships and relevant information about others involved in purchase or use.
- personal_conditions: needs, capabilities, sensitivities, or constraints the person reports about themself.

## usage_patterns
How the person buys, prepares, uses, stores, and repurchases these products, each with scope, context, behavior, evidence.
Describe an activity at the level its evidence supports: a stated routine or repeated accounts support a pattern; one episode stays one episode; a plan stays a plan ("intends to").

## product_preferences
Selection criteria on five axes. One item per criterion and scope: combine every review that judged that aspect, rather than one item per review.
Brand items are attitudes toward brands, lines, or named products; a favorite or avoided product is named in the preference as that product, not its whole brand. A single evaluation of one product keeps that product as its scope.
- brand: named brands, product lines, or products the person favors or avoids. The store field is not necessarily the brand.
- price: sensitivity, value judgments, willingness to pay, and trade-offs against other aspects.
- review: how the person uses or judges other people's reviews.
- functional: contents, ingredients, materials, specifications, compatibility, size, packaging, preparation effort, and performance.
- subjective: experienced qualities such as taste, aroma, texture, sound, comfort, appearance, and style.
Shipping, courier, and service-only opinions are outside these axes.

# 4. Item content
Each preference item states:
- scope: the products the attitude ranges over. For a criterion, that is what the person is choosing among; for a single evaluation of one product, it is that product. Whatever makes the person prefer one product over another (a feature, flavor, format, brand, or a named product) is the preference, never the scope. The scope is narrower than the product type only when the person ties the attitude to a narrower range in their own words ("for decaf, I..."). Occasions, purposes, and recipients go in context; the products they reviewed are evidence.
- preference: whose attitude it is, the aspect, the result they want, and any exception, compromise, condition, or change.
- context, each a string or null:
  - for_whom: the intended user/beneficiary of the choice, not the attitude-holder; the user by default; null only when the passage concerns no particular person.
  - when, where, purpose: only what the text states as the time, place, or aim of the activity or criterion. A product's suggested use is not the person's aim.
- strength: required only for a necessity or exclusion the person states; preferred for a like, dislike, relative choice, or favorite; unspecified when the attitude is supported but its level is unclear. Enthusiasm, repetition, or a tolerated compromise does not make a criterion required.

Level check, after the scope is set: a preference item should name an aspect that can be checked on any product within its scope, together with the result the person wants. If its content has become a value word (quality, reliability, health, style), rewrite it as the aspect the person actually judged. The check never turns a single evaluation of one product into a criterion.

# 5. Evidence
Every item has evidence with a reviews array identifying the reviews that support it.
Each evidence entry has review_id, quote, evidence_type. Copy the review ID exactly.
A quote is one continuous verbatim span of that record's review_title or review_text, long enough to show who, what, and any condition. Do not translate, edit, join, or shorten it, and do not insert ellipses. Cite every review that supports the item and none that does not.
evidence_type describes the quoted span itself, the same way wherever it is cited:
- explicit_preference: the person states a taste, choice rule, or relative preference.
- aspect_evaluation: satisfaction or dissatisfaction with a specific aspect, performance, or use outcome.
- overall_evaluation: an attitude toward a product as a whole.
- fact_or_usage: a personal circumstance, activity, experience, or concrete intention.
- product_description: an observation with no evaluative stance.
For a span that mixes kinds, use the first that applies in this order: explicit_preference, aspect_evaluation, overall_evaluation, fact_or_usage, product_description.

# 6. Examples
Synthetic; not input facts. Do not copy them into the result.

1. Same aspect across products, mixed results.
   "Battery got me through a 12-hour flight." / "Died after 3 hours, so I sent them back." / "Only 6 hours of battery, but for $20 I'll take it."
   - Too narrow: three items, one per pair of headphones.
   - Too abstract: "Values reliable, high-quality headphones."
   - At the right level: functional, scope wireless headphones: "The user chooses headphones by battery life and wants it to last a long day; they accept a shorter battery life when the price is low." Evidence: all three quotes.
2. One product's feature, praised once.
   "The auto shut-off on this kettle is a nice touch."
   - Keep it at this kettle's scope, or attach it to a criterion it illustrates. It does not show that the user requires auto shut-off on every kettle.
3. A general rule stated once.
   "I never buy pans with a nonstick coating."
   - A general functional item for pans, strength required, even though it appears in one review.
4. What a statement asserts.
   "These bars would be great for hiking" evaluates the product and creates no hiking activity or criterion.
   "I take these bars on every hike" reports a usage pattern.
   "For hiking, I pick bars that don't melt" states a criterion conditional on hiking.
5. Change and attribution.
   "Brand A used to be my go-to, but their last two bottles leaked, so I switched to Brand B. My son still prefers Brand A's taste."
   - Brand: Brand B is the user's current choice after leaks in Brand A; Brand A was a past favorite.
   - Functional, about bottles: the user rejects bottles that leak; they switched brands over it.
   - People: the son prefers Brand A's taste; that is the son's preference, not the user's.

# 7. Final check
- Each item says something concrete about this person, with its scope set as Section 4 defines.
- No item is one review restated when other reviews judged the same aspect.
- Every claim, scope, condition, exception, and strength holds for all of its cited evidence.
- Nothing about the person comes from metadata, ratings, dates, or what the products have in common.
Output exactly one JSON object matching the schema below. Write it in English; keep names and quotations in their original language.

# 8. Output JSON Schema
The output object must match this JSON Schema:
