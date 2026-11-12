# Larkspur decision log

Decisions are numbered in the order they were made. Each records the decision, the reason, and who decided.

## D-07 (2026-06-12): Native apps, not a web app

Decision: build native iOS and Android apps with a shared core.
Reason: technicians work offline in basements and plant rooms; the web prototype failed offline tests.
Decided by: Marcus Lee, Priya Raman.

## D-09 (2026-07-03): Quillmark for push notifications

Decision: use Quillmark as the push notification vendor.
Reason: lowest cost per message of the three vendors evaluated, and UK data residency.
Alternative considered: building on the platform push services directly (rejected: two engineers for a quarter).
Decided by: Marcus Lee.

## D-11 (2026-08-19): Seat-based pricing

Decision: price per technician seat, billed monthly.
Reason: pilot customers budget per headcount.
Decided by: Priya Raman, with finance.

## D-14 (2026-10-30): Move the launch to 15 February 2027

Decision: move the public launch from 20 January 2027 to 15 February 2027.
Reason: the identity team cannot finish single sign-on for the second pilot customer before 15 January 2027,
and launch criterion 2 requires it. Four weeks of slack were added for app store review.
Decided by: Priya Raman, approved by the steering group.

## D-15 (2026-11-04): Keep the accessibility audit vendor for launch

Decision: retain the same accessibility auditor for a pre-launch re-check in January.
Reason: the October pre-audit found minor issues only; a re-check after the SSO screens are added is cheap.
Decided by: Dana Ortiz.
