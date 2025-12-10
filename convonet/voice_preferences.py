"""
Voice Preferences Management
Stores and retrieves user voice preferences for ElevenLabs TTS
"""

import json
import logging
from typing import Optional, Dict, Any
from convonet.redis_manager import get_redis_manager

logger = logging.getLogger(__name__)


class VoicePreferences:
    """Manages voice preferences for users"""
    
    def __init__(self):
        self.redis = get_redis_manager()
    
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """
        Get user's voice preferences
        
        Returns:
            Dict with voice preferences or defaults
        """
        if not self.redis.is_available():
            return self._get_default_preferences()
        
        try:
            key = f"voice_preferences:{user_id}"
            data = self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"❌ Error getting voice preferences: {e}")
        
        return self._get_default_preferences()
    
    def update_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        """
        Update user's voice preferences
        
        Args:
            user_id: User ID
            preferences: Dict with voice preferences
            
        Returns:
            True if successful
        """
        if not self.redis.is_available():
            return False
        
        try:
            key = f"voice_preferences:{user_id}"
            # Merge with existing preferences
            existing = self.get_user_preferences(user_id)
            existing.update(preferences)
            # Store for 90 days
            self.redis.set(key, json.dumps(existing), expire=86400 * 90)
            return True
        except Exception as e:
            logger.error(f"❌ Error updating voice preferences: {e}")
            return False
    
    def get_voice_id(self, user_id: Optional[str]) -> Optional[str]:
        """Get user's preferred voice ID"""
        if not user_id:
            return None
        prefs = self.get_user_preferences(user_id)
        return prefs.get("voice_id")
    
    def get_language(self, user_id: Optional[str]) -> str:
        """Get user's preferred language (default: 'en')"""
        if not user_id:
            return "en"
        prefs = self.get_user_preferences(user_id)
        return prefs.get("language", "en")
    
    def get_emotion_enabled(self, user_id: Optional[str]) -> bool:
        """Check if emotion detection is enabled for user"""
        if not user_id:
            return True  # Default enabled
        prefs = self.get_user_preferences(user_id)
        return prefs.get("emotion_enabled", True)
    
    def get_style(self, user_id: Optional[str]) -> str:
        """Get user's preferred style (default: 'conversational')"""
        if not user_id:
            return "conversational"
        prefs = self.get_user_preferences(user_id)
        return prefs.get("style", "conversational")
    
    def _get_default_preferences(self) -> Dict[str, Any]:
        """Get default voice preferences"""
        return {
            "voice_id": None,  # Use default ElevenLabs voice
            "language": "en",
            "emotion_enabled": True,
            "style": "conversational",
            "stability": 0.5,
            "similarity_boost": 0.75,
            "use_elevenlabs": True  # Use ElevenLabs by default if available
        }


# Global instance
_voice_preferences = None


def get_voice_preferences() -> VoicePreferences:
    """Get global voice preferences instance"""
    global _voice_preferences
    if _voice_preferences is None:
        _voice_preferences = VoicePreferences()
    return _voice_preferences

