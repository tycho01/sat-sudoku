'''generic functions related to Davis-Putnam not specific to sudoku'''
import time
import logging
from collections import defaultdict
import pickle

# constants

U = 0
Y = 1
N = -1
EYE = lambda x: x

# classes

class State:
    '''container for our solver state'''
    rules: dict
    facts: dict
    occurrences: dict
    due_pure: set
    due_unit: set

    def __init__(self, rules):
        self.rules = rules
        self.facts = {}
        occ = {belief: get_occurrences(rules, belief) for belief in [Y, N]}
        self.occurrences = occ
        y_idxs = set(occ[Y].keys())
        n_idxs = set(occ[N].keys())
        self.due_pure = y_idxs.union(n_idxs) - y_idxs.intersection(n_idxs)
        self.due_unit = {line for line, ors in rules.items() if len(ors) == 1}

# Necessary Helper Functions

def add_fact(state, var, belief):
    '''add a fact'''
    assert belief != U
    state.facts[var] = belief
    for fact in [Y, N]:
        # replace variable occurrences
        # for line in list(state.occurrences[fact].get(var, [])) if line in state.rules:
        for line in list(state.occurrences[fact].get(var, [])):
            if line in state.rules:
                rule = state.rules[line]
                if belief == fact:
                    # data agrees, OR rule satisfied, ditch whole rule
                    for key, val in rule.items():
                        occs = state.occurrences[val].get(key, set())
                        occs.discard(line)
                        if not occs:
                            # check occurrences opposite belief
                            if state.occurrences[-val].get(key, set()):
                                # other exists: pure literal clause
                                state.due_pure.add(key)
                            else:
                                # if both empty ditch both
                                state.occurrences[Y].pop(key, None)
                                state.occurrences[N].pop(key, None)
                    state.rules.pop(line, None)
                else:
                    # data opposite, ditch option from rule
                    rule.pop(var, None)
                    if not rule:
                        # empty clause: clash
                        return (N, state)
                    if len(rule) == 1:
                        # 1 left: unit clause
                        state.due_unit.add(line)
        state.occurrences[fact].pop(var, None)      # timing?
    state.due_pure.discard(var)
    return (Y, state)

def parse_dimacs_row(row):
    '''parse a line from a dimacs file into a dict, or None in case of a tautology'''
    dic = {}
    for term in row.split(' ')[:-1]:
        is_neg = term[0] == '-'
        key = int(term[1:]) if is_neg else int(term)
        val = N if is_neg else Y
        if key not in dic:
            dic[key] = val
        elif dic[key] != val:
            # different truth value known for this key, tautology detected
            return None
    return dic

def parse_dimacs(dimacs_file_contents):
    '''parse a dimacs file to rules (dict of dicts), cleaning out tautologies'''
    clause_dict = {}
    rows = list(filter(lambda s: s[0] not in ['c', 'p', 'd'], dimacs_file_contents))
    for (i, row) in enumerate(rows):
        clause = parse_dimacs_row(row)
        # skip tautologies
        if clause:
            clause_dict[i] = clause
    return clause_dict

def read_file(path):
    '''read a file and parse its lines'''
    with open(path) as file:
        lines = file.readlines()
    return parse_dimacs(lines)

def write_dimacs(path, facts, ser_fn=str):
    '''write facts to a DIMACS format file based on a serialization function, incl. final 0s'''
    strn = '\n'.join([f'{"-" if v == N else ""}{ser_fn(k)} 0' for k, v in facts.items() if v != U])
    with open(path, 'w') as file:
        file.write(strn)

def simplify(state):
    '''apply pure / unit clause rules until stuck.
    returns (satisfiability, rules, facts).'''
    global unit_applied, pure_applied
    while state.due_pure or state.due_unit:

        # https://python.org/dev/peps/pep-0572/
        while True:
            var = state.due_pure.pop() if state.due_pure else None
            if not var:
                break

            # pure literal rule: regard occurrences as true if they all agree
            belief = Y if state.occurrences[Y].get(var, set()) else N
            if (Y if state.occurrences[N].get(var, set()) else N) != belief:

                try:
                    pure_applied += 1
                except NameError:
                    pure_applied = 1

                (sat, state) = add_fact(state, var, belief)
                if sat == N:
                    return (sat, state)

        # https://python.org/dev/peps/pep-0572/
        while True:
            line = state.due_unit.pop() if state.due_unit else None
            if not line:
                break

            # unit clause rule: regard sole clauses as true
            if line in state.rules:
                rule = state.rules[line]
                if rule:
                    [(var, belief)] = list(rule.items())

                    try:
                        unit_applied += 1
                    except NameError:
                        unit_applied = 1

                    (sat, state) = add_fact(state, var, belief)
                    if sat == N:
                        return (sat, state)

    sat = U if state.rules else Y
    return (sat, state)

def split(state_, facts_printer, fact_printer, guess_fn, fancy_beliefs=False):
    '''guess a fact to proceed after simplify fails.'''
    global splits, backtracks
    state = pickle.loads(pickle.dumps(state_, -1))
    guess_fact, guess_value = guess_fn(state.rules, state.occurrences)
    print_fact = fact_printer(guess_fact)

    try:
        splits += 1
    except NameError:
        splits = 1

    logging.info('guess     %d: %d', print_fact, guess_value)
    logging.debug(facts_printer(state.facts))
    if fancy_beliefs:
        guess_value = Y
        # guess_value = -guess_value
    (sat, state) = add_fact(state, guess_fact, guess_value)
    if sat != N:
        (sat, state) = simplify(state)
        if sat == U:
            (sat, state) = split(state, facts_printer, fact_printer, guess_fn, fancy_beliefs)
    if sat == N:
        # clash detected, backtrack
        corrected = -guess_value  # opposite of guess
        (sat, state) = add_fact(state_, guess_fact, corrected)
        if sat == N:
            return (sat, state)
        # TODO: backtrack to assumption of clashing fact?

        try:
            backtracks += 1
        except NameError:
            backtracks = 1

        logging.info('backtrack %d: %d', print_fact, corrected)
        logging.debug(facts_printer(state.facts))
        (sat, state) = simplify(state_)
        if sat == U:
            (sat, state) = split(state, facts_printer, fact_printer, guess_fn, fancy_beliefs)
    return (sat, state)

def get_occurrences(rules, belief):
    '''get rule occurrences for a belief, e.g. { 123: set([3, 10]) }'''
    belief_occurrences = defaultdict(lambda: set())
    for line, ors in rules.items():
        for key, val in ors.items():
            if val == belief:
                # TODO: find alternative to this snippet that doesn't add 0.07s
                idx_set = belief_occurrences.get(key, set())
                idx_set.add(line)
                belief_occurrences[key] = idx_set
    return dict(belief_occurrences)

def solve_csp(rules, out_file, guess_fn, fact_printer=dict, fancy_beliefs=False):
    '''solve a general CSP problem and write its solution to a file. returns satisfiability.'''
    start = time.time()
    global splits, backtracks, unit_applied, pure_applied
    splits = 0
    backtracks = 0
    unit_applied = 0
    pure_applied = 0

    try:
        logging.debug('initialization')
        state = State(rules)
        logging.debug(fact_printer(state.facts))

        logging.debug('simplify')
        (sat, state) = simplify(state)
        assert sat != N
        logging.debug(fact_printer(state.facts))

        logging.debug('split to answer')
        if sat == U:
            (sat, state) = split(state, fact_printer, EYE, guess_fn, fancy_beliefs)
        assert sat != N
    except AssertionError:
        pass
    secs = time.time() - start
    logging.debug('final solution')

    # output DIMACS file 'filename.out' with truth assignments, empty if unsolved
    content = state.facts if sat else {}
    write_dimacs(out_file, content)
    solved = sat == Y
    return (solved, state, secs, splits, backtracks, unit_applied, pure_applied)
