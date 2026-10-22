# Lebenflo Credit Union – Consumer Lending Intake Policy

> **Fictional document.** Lebenflo Credit Union does not exist. This policy was written for a
> portfolio demonstration and is not lending, legal or compliance guidance.

## LP-1 Purpose and scope
This policy governs the intake review of consumer loan applications (auto, home improvement and
debt consolidation loans) before they reach an underwriter. Intake confirms that an application
packet is complete, internally consistent and legible. Intake does not assess creditworthiness
and does not approve or decline credit.

## LP-2 Required documents
Every consumer loan packet must contain four documents: the most recent pay stub, the prior
year's IRS Form W-2, the most recent monthly statement for the member's primary deposit account,
and an unexpired government-issued photo identification such as a driver's license. A packet
missing any required document is incomplete. Incomplete packets are routed to a member services
reviewer, who contacts the member to request the missing item before underwriting begins.

## LP-3 Identity and name consistency
The applicant's legal name must be consistent across the identification document, the pay stub,
the W-2 and the account statement. Differences in letter case, spacing or punctuation are not
discrepancies. Any other difference, including a nickname, a different middle or last name, or a
recent name change, must be reviewed by a person, who may request supporting documentation such
as a marriage certificate or a corrected W-2. Name discrepancies are a common indicator of both
benign clerical issues and identity fraud and must never be resolved automatically.

## LP-4 Income verification
Current income is verified by annualizing the gross pay on the most recent pay stub according to
the pay frequency (weekly ×52, biweekly ×26, semimonthly ×24, monthly ×12). The annualized figure
is compared with wages, tips and other compensation reported in Box 1 of the prior-year W-2.
A difference greater than 10 percent requires human review. Acceptable explanations include a
raise, a promotion, a change of employer, or a partial year of employment, and the reviewer
documents which explanation applies.

## LP-5 Debt-to-income guideline
Underwriters evaluate the debt-to-income ratio, defined as total monthly debt payments including
the proposed loan payment divided by gross monthly income. The guideline maximum for unsecured
consumer loans is 40 percent and for secured auto loans 45 percent. Debt-to-income is assessed
at underwriting, not at intake.

## LP-6 Automated document extraction and data quality
Automated extraction tools may be used to read documents. Every value used in an intake check
must be extracted with a confidence of at least 0.80, or verified by a person. Values below the
threshold, or values that could not be read, are flagged for manual verification against the
original document. Staff must not override a low-confidence value without viewing the source
document.

## LP-7 Routing outcomes
Intake has exactly two outcomes. A packet that passes every intake check is routed to
underwriting ("approve for underwriting"). A packet with any finding is escalated to a human
intake reviewer with the reasons listed. Automated intake must never decline an application.
Any adverse action, including a decline or counteroffer, is decided by a qualified person and
communicated with the notices required by the Equal Credit Opportunity Act.

## LP-8 Protection of member information
Social Security numbers, account numbers and dates of birth are restricted member information.
They may be processed by approved document-processing services but must be masked before any
text is sent to a generative AI model. Logs must store references or hashes of documents, not the
restricted values themselves.

## LP-9 Audit trail
Every intake decision must be traceable. The audit record captures the time, the processing
step, the system or person responsible, the model and version used, confidence scores and the
reasons for the outcome. Audit records are retained for seven years.

## LP-10 Use of generative AI
Generative AI may summarize findings for a reviewer and may assist in reading documents that
standard extraction cannot process. Generative AI must not make or recommend credit decisions.
Summaries must be grounded in the packet's extracted data and this policy, and reviewers remain
responsible for verifying them.
