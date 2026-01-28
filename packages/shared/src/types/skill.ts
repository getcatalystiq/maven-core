/**
 * Skill types
 */

export interface Skill {
  id: string;
  tenantId: string;
  name: string;
  description: string;
  r2Path: string;
  roles?: string[];
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface SkillContent {
  name: string;
  description: string;
  prompt: string;
  roles?: string[];
  tools?: string[];
  agents?: string[];
}

export interface SkillAssignment {
  id: string;
  tenantId: string;
  userId: string;
  skillId: string;
  enabled: boolean;
}

export interface SkillCreateRequest {
  name: string;
  description: string;
  content: string;  // SKILL.md content
  roles?: string[];
}

export interface SkillUpdateRequest {
  description?: string;
  content?: string;
  roles?: string[];
  enabled?: boolean;
}

export interface SkillListResponse {
  skills: Skill[];
  total: number;
  offset: number;
  limit: number;
}
