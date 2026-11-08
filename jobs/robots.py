"""robots.txt matching as specified in RFC 9309.

Python's urllib.robotparser applies the first rule that matches, so a file such as

    User-agent: *
    Disallow: /
    Allow: /api/

blocks /api/ there, while RFC 9309 (and every major crawler) uses the longest matching
rule, with Allow winning a tie. This module follows the RFC.
"""
import re
import urllib.parse


def _rx(path):
    end = path.endswith("$")
    p = re.escape(path[:-1] if end else path).replace(r"\*", ".*")
    return re.compile(p + ("$" if end else ""))


class Robots:
    def __init__(self, text="", disallow_all=False):
        self.disallow_all = disallow_all
        self.groups = []                       # [(agents, [(allow, pattern, regex)])]
        agents, rules, last_was_agent = [], [], False
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = (s.strip() for s in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                if not last_was_agent and (agents or rules):
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
                last_was_agent = True
            elif field in ("allow", "disallow"):
                last_was_agent = False
                if agents and value:
                    rules.append((field == "allow", value, _rx(value)))
                elif agents and field == "disallow":
                    pass                      # "Disallow:" with no path allows everything
        if agents or rules:
            self.groups.append((agents, rules))

    def _rules_for(self, ua):
        token = ua.split("/")[0].strip().lower()
        mine = [r for a, rs in self.groups if token in a for r in rs]
        if any(token in a for a, _ in self.groups):
            return mine
        return [r for a, rs in self.groups if "*" in a for r in rs]

    def can_fetch(self, ua, url):
        return self.match(ua, url)[0]

    def match(self, ua, url):
        """(allowed, the rule that decided it), so refusals can be logged with their reason."""
        if self.disallow_all:
            return False, "robots.txt unreachable"
        p = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(p.path or "/") + (("?" + p.query) if p.query else "")
        best = None                            # (length, allow, pattern)
        for allow, pat, rx in self._rules_for(ua):
            if rx.match(path):
                if best is None or (len(pat), allow) > best[:2]:
                    best = (len(pat), allow, pat)
        if best is None:
            return True, ""
        return best[1], ("Allow: " if best[1] else "Disallow: ") + best[2]
