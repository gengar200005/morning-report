"""Verify the year-end filing's own disclosures against separately filed nine-month totals."""

# Every component is a consolidated KRW observation in one filed annual statement.
# The period mapper in pit_facts resolves these names independently for each fiscal year.
FIRST_NINE = (
    ('first9',),
    ('first6', 'third3'),
    ('first3', 'second3', 'third3'),
)
SIDES = ('current', 'prior')


def annual_basis(evidence_rows, field, nine_pair, derived_pair):
    """Check the current and prior fiscal years within the same annual source bytes."""
    if field not in ('revenue', 'operating_profit'):
        raise ValueError('unsupported income statement field')
    documents = []
    accepted = False
    blocked = False
    for sha, evidence in evidence_rows:
        sides = {}
        for side, expected_nine, expected_fourth in zip(SIDES, nine_pair, derived_pair, strict=True):
            column = field + '_' + side
            observations = {}
            conflicts = []
            proofs = []
            for key in ('3', 'first9', 'first6', 'first3', 'second3', 'third3'):
                item = evidence.get(key, {}).get(column, {})
                if item.get('status') in ('conflicting_values', 'source_disagreement'):
                    conflicts.append('conflicting_' + key)
                if type(item.get('value')) is int:
                    observations[key] = item
            for components in FIRST_NINE:
                if all(key in observations for key in components):
                    total = sum(observations[key]['value'] for key in components)
                    (proofs if total == expected_nine else conflicts).append('+'.join(components))
            if '3' in observations:
                matches = observations['3']['value'] == expected_fourth
                (proofs if matches else conflicts).append('direct_fourth_quarter')
            if all(key in observations for key in ('first6', 'first3', 'second3')):
                if observations['first6']['value'] != observations['first3']['value'] + observations['second3']['value']:
                    conflicts.append('inconsistent_first_half')
            if observations or conflicts:
                sides[side] = dict(proofs=proofs, conflicts=conflicts, observations=observations)
            blocked |= bool(conflicts)
        if sides:
            documents.append(dict(sha256=sha, sides=sides))
        accepted |= all(sides.get(side, {}).get('proofs') for side in SIDES)
    if blocked:
        return 'BLOCKED', dict(reason='annual_conflicts_with_cumulative_inputs', documents=documents)
    if accepted:
        return 'PASS', dict(reason='both_years_reconciled_in_submitted_annual', documents=documents)
    return 'INSUFFICIENT', dict(reason='annual_lacks_complete_reconciliation', documents=documents)
