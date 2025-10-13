#!/usr/bin/env python3
"""
Script til at finde potentielt ubrugte metoder i Python kodebase.
Kombinerer AST parsing med grep-baseret søgning for at identificere metoder
der kun defineres men aldrig kaldes.
"""

import ast
from pathlib import Path
from typing import Dict, List


class MethodCollector(ast.NodeVisitor):
    """AST visitor der samler alle metode definitioner."""
    
    def __init__(self):
        self.methods = []
        self.classes = []
        
    def visit_FunctionDef(self, node):
        """Besøg funktions definitoner."""
        # Skip private methods og special methods som er mindre sandsynlige at være ubrugte
        if not node.name.startswith('_'):
            self.methods.append({
                'name': node.name,
                'line': node.lineno,
                'type': 'function',
                'class': self.classes[-1] if self.classes else None
            })
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        """Besøg klasse definitioner."""
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()


def analyze_file(file_path: Path) -> List[Dict]:
    """Analyser en Python fil for metode definitioner."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        collector = MethodCollector()
        collector.visit(tree)
        
        # Tilføj fil information
        for method in collector.methods:
            method['file'] = str(file_path)
            
        return collector.methods
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}")
        return []


def find_method_references(method_name: str, root_dir: Path) -> List[str]:
    """Find referencer til en metode i alle Python filer."""
    references = []
    
    # Søg efter forskellige call patterns
    patterns = [
        f".{method_name}(",  # instance.method()
        f" {method_name}(",  # function_call()
        f"={method_name}(",  # assignment
        f"({method_name})",  # parameter
    ]
    
    for py_file in root_dir.rglob("*.py"):
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            for pattern in patterns:
                if pattern in content:
                    # Count occurrences 
                    count = content.count(pattern)
                    if count > 0:
                        references.append(f"{py_file}:{count}")
        except Exception:
            continue
            
    return references


def main():
    """Hovedfunktion der kører analysen."""
    root_dir = Path("app")
    
    print("🔍 Analyserer Python filer for metode definitioner...")
    
    all_methods = []
    
    # Samle alle metoder
    for py_file in root_dir.rglob("*.py"):
        methods = analyze_file(py_file)
        all_methods.extend(methods)
    
    print(f"📊 Fandt {len(all_methods)} metoder i totalt")
    
    # Analyse for hver metode
    potentially_unused = []
    
    for method in all_methods:
        method_name = method['name']
        
        # Skip common method names der sandsynligvis bruges
        if method_name in ['main', 'run', 'start', 'stop', 'init', 'setup', 'cleanup']:
            continue
            
        references = find_method_references(method_name, root_dir)
        
        # Filter ud hvis metoden kun findes i sin egen definitionsfil
        external_refs = [ref for ref in references if not ref.startswith(method['file'])]
        
        if len(external_refs) == 0:
            potentially_unused.append({
                **method,
                'references': references
            })
    
    # Print resultater
    print(f"\n🚨 Fandt {len(potentially_unused)} potentielt ubrugte metoder:")
    print("=" * 80)
    
    # Group by file
    by_file = {}
    for method in potentially_unused:
        file_path = method['file']
        if file_path not in by_file:
            by_file[file_path] = []
        by_file[file_path].append(method)
    
    for file_path, methods in sorted(by_file.items()):
        print(f"\n📁 {file_path}")
        for method in methods:
            class_info = f" (in {method['class']})" if method['class'] else ""
            ref_info = f" - {len(method['references'])} local refs" if method['references'] else " - no refs found"
            print(f"  🔸 {method['name']}{class_info} (line {method['line']}){ref_info}")
    
    print(f"\n💡 Tip: Tjek disse metoder manuelt - nogle kan være:")
    print("  - API endpoints (kaldet udefra)")  
    print("  - Event handlers")
    print("  - Dynamisk kaldet via getattr() eller reflection")
    print("  - Test utilities")
    print("  - Future features")


if __name__ == "__main__":
    main()