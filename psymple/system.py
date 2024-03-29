from bisect import bisect
from scipy.integrate import solve_ivp
from numpy import linspace

import matplotlib.pyplot as plt
import networkx as nx

from psymple.globals import T
from psymple.variables import (
    Parameters,
    SimParameter,
    SimUpdateRule,
    SimVariable,
    Variable,
    Variables,
)


class PopulationSystemError(Exception):
    pass


class System:
    def __init__(self, population):
        self.time = SimVariable(Variable(T, 0.0, "system time"))
        self.time.set_update_rule(
            SimUpdateRule(
                self.time,
                "1",
                Variables(),
                Parameters(),
                "system time",
            )
        )
        self.variables = self._create_variables(population.variables)
        self.parameters = self._create_parameters(population.parameters)
        self._assign_update_rules(population.update_rules)

    def _create_variables(self, variables):
        for variable in variables:
            if variable.initial_value is None:
                # print(f"Warning: Variable {variable.symbol} has no initial value")
                variable.initial_value = 0
        return Variables([SimVariable(variable) for variable in variables])

    def _create_parameters(self, parameters):
        for parameter in parameters:
            if parameter.value is None:
                raise PopulationSystemError(
                    f"Parameter {parameter.symbol} has no value"
                )
        return Parameters([SimParameter(parameter) for parameter in parameters])

    def _assign_update_rules(self, update_rules):
        combined_update_rules = update_rules._combine_update_rules()
        for rule in combined_update_rules:
            new_rule = SimUpdateRule.from_update_rule(
                rule, self.variables + self.time, self.parameters
            )
            # variable = self.variables[rule.variable.symbol]
            variable = new_rule.variable
            variable.set_update_rule(new_rule)
        for variable in self.variables:
            if variable.update_rule is None:
                # print(f"Warning: Variable {variable.symbol} has no update rule.")
                variable.set_update_rule(SimUpdateRule(variable))
        for parameter in self.parameters:
            parameter.initialize_update_rule(
                self.variables + self.time, self.parameters
            )

    def _compute_parameter_update_order(self):
        variable_symbols = {v.symbol for v in self.variables + self.time}
        parameter_symbols = {p.symbol: p for p in self.parameters}
        G = nx.DiGraph()
        G.add_nodes_from(parameter_symbols)
        for parameter in self.parameters:
            parsym = parameter.symbol
            for dependency in parameter.dependent_parameters():
                if dependency.symbol in parameter_symbols:
                    G.add_edge(dependency.symbol, parsym)
                elif dependency.symbol not in variable_symbols:
                    raise PopulationSystemError(
                        f"Parameter {parsym} references undefined symbol {dependency}"
                    )
        try:
            nodes = nx.topological_sort(G)
            ordered_parameters = [parameter_symbols[n] for n in nodes]
        except nx.exception.NetworkXUnfeasible:
            raise PopulationSystemError(
                f"System parameters contain cyclic dependencies"
            )
        return ordered_parameters

    def _compute_substitutions(self):
        self.parameters = Parameters(self._compute_parameter_update_order())
        for parameter in self.parameters:
            parameter.substitute_parameters(self.variables + self.time)
        for variable in self.variables:
            variable.substitute_parameters(self.variables + self.time)

    def _wrap_for_solve_ivp(self, t, y):
        """
        returns a callable function of all system variables for use with solve_ivp,
        wrapping lambdified update rules
        """
        for variable in self.variables:
            if variable.update_rule._equation_lambdified is None:
                variable.update_rule._lambdify()

        return [
            v.update_rule._equation_lambdified(
                **{
                    p: y[self.variables.objects.index(self.variables[p])]
                    if p != "T"
                    else t
                    for p in v.update_rule._equation_lambdified.__code__.co_varnames
                }
            )
            for v in self.variables
        ]

    def _advance_time(self, time_step):
        self.time.update_buffer()
        for variable in self.variables:
            variable.update_buffer()
        for variable in self.variables:
            variable.update_time_series(time_step)
        self.time.update_time_series(time_step)

    def _advance_time_unit(self, n_steps):
        if n_steps <= 0 or not isinstance(n_steps, int):
            raise ValueError(
                "Number of time steps in a day must be a positive integer, "
                f"not '{n_steps}'."
            )
        for i in range(n_steps):
            self._advance_time(1 / n_steps)

    def simulate(self, t_end, n_steps, mode):
        if t_end <= 0 or not isinstance(t_end, int):
            raise ValueError(
                "Simulation time must terminate at a positive integer, "
                f"not '{t_end}'."
            )
        self._compute_substitutions()
        if mode == "discrete" or mode == "dscr":
            print("dscr")
            for i in range(t_end):
                self._advance_time_unit(n_steps)
        elif mode == "continuous" or mode == "cts":
            print("cts")
            sol = solve_ivp(self._wrap_for_solve_ivp, [0,t_end], self.variables.get_final_values(), dense_output = True)
            t = linspace(0, t_end, n_steps * t_end + 1)
            self.time.time_series = t
            for variable in self.variables:
                variable.time_series = sol.sol(t)[self.variables.objects.index(variable)]


    def plot_solution(self, variables, t_range=None):
        t_series = self.time.time_series
        if t_range is None:
            sl = slice(None, None)
        else:
            lower = bisect(t_series, t_range[0])
            upper = bisect(t_series, t_range[1])
            sl = slice(lower, upper)
        if isinstance(variables, set):
            variables = {v: {} for v in variables}
        legend = []
        for var_name, options in variables.items():
            variable = self.variables[var_name]
            if isinstance(options, str):
                plt.plot(t_series[sl], variable.time_series[sl], options)
            else:
                plt.plot(t_series[sl], variable.time_series[sl], **options)
            legend.append(variable.symbol.name)
        plt.legend(legend, loc="best")
        plt.xlabel("time")
        plt.grid()
        plt.show()