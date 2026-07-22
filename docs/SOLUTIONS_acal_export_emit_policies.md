from typing import Dict, Any, List

class CapabilityMap:
    """Represents the loaded YAML mapping for a target language."""
    def __init__(self, language_id: str):
        # Maps ACAL Feature ID (string) -> Capability Data (dict)
        self.features: Dict[str, Dict] = {} 
        # Example structure: {"ForAny": {"is_supported": False, "reason": "Cedar lacks quantified scopes."}}
    
    def get_capability(self, feature_id: str) -> Dict:
        """Retrieves the capability entry for a given ACAL feature."""
        return self.features.get(feature_id, {})


class ACALExporter:
    """Core exporter engine responsible for transforming and validating the AST."""

    def __init__(self, acal_document: Any, target_language: str):
        # 1. Load the capability matrix immediately.
        self.capabilities = self._load_capability_map(target_language)
        self.ast = acal_document # Assume already parsed ACAL AST structure

    def _validate_and_rewrite(self, node: Any) -> tuple[Any, List[str]]:
        """
        Recursively traverses the AST node. Returns (rewritten_node, list_of_warnings/errors).
        This function enforces all export rules.
        """
        warnings = []
        
        # Example check for a specific ACAL feature: SharedVariableDefinition
        if hasattr(node, 'SharedVariableDefinition'):
            cap_data = self.capabilities.get('SharedVariableDefinition')

            if not cap_data['is_supported']:
                # --- Core Failure Point Handling ---
                error_msg = (f"Error: Cannot export SharedVariableDefinition to {self.target_language}. "
                             f"Reason: {cap_data['reason']}")

                if self.config.strict and not self._should_ignore(node):
                    raise TranslationFailure(error_msg)
                elif self.config.warn_downgrade:
                    warnings.append(f"[WARNING - DOWGRADE]: Lost SharedVariableDefinition semantics.")
                    # Silently skip the node for best-effort, logged compilation
                    return None, warnings 
            
        # General traversal logic...
        if isinstance(node, list):
             rewritten_list = []
             for item in node:
                 item, ws = self._validate_and_rewrite(item)
                 if item is not None:
                     rewritten_list.append(item)
                     warnings.extend(ws)
             return rewritten_list, warnings

        # If validation passes and rewrites are applied (e.g., combining alg swapping)
        return node, warnings


    def export(self) -> str:
        """Executes the full conversion process."""
        try:
            rewritten_ast, accumulated_warnings = self._validate_and_rewrite(self.ast)
        except TranslationFailure as e:
             # Handle immediate halt from --strict mode
             return f"Export Failure ({self.target_language}): {e}"

        # 3. Phase III: Emission
        emitter = LanguageEmitterFactory.get_emitter(self.target_language)
        return emitter.emit(rewritten_ast)


# Custom Exception for controlled failure signaling
class TranslationFailure(Exception):
    """Raised when a critical semantic gap is detected in strict mode."""
    pass