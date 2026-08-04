# frozen_string_literal: true

require "minitest/autorun"
require "json"
require "yaml"

ROOT = File.expand_path("..", __dir__)
MACHINE = YAML.safe_load(File.read(File.join(ROOT, "references", "machine.yaml")), aliases: false)
FIXTURES = YAML.safe_load(File.read(File.join(__dir__, "fixtures", "paths.yaml")), aliases: true)
SKILL_TEXT = File.read(File.join(ROOT, "SKILL.md"))
CONTEXT_SCHEMA = JSON.parse(File.read(File.join(ROOT, "references", "context.schema.json")))
JUSTFILE_TEXT = File.read(File.join(ROOT, "justfile"))
START_HARNESS_TEXT = File.read(File.join(ROOT, "scripts", "start-harness"))
PLAY_SEARCH_TEXT = File.read(File.join(ROOT, "scripts", "play-search"))

class MachineConformanceTest < Minitest::Test
  def transition(state, event, guards = {})
    branches = MACHINE.dig("states", state, "on", event)
    raise KeyError, "#{state} does not accept #{event}" unless branches

    selected = branches.find do |branch|
      guard = branch["guard"]
      guard.nil? || guards.fetch(guard, false)
    end
    raise KeyError, "#{state}.#{event} has no satisfied branch" unless selected

    selected.fetch("target")
  end

  FIXTURES.fetch("cases").each do |fixture|
    define_method("test_#{fixture.fetch('name').gsub(/[^a-z0-9]+/i, '_')}") do
      visited = []
      current = fixture.fetch("steps").first.fetch("state")

      fixture.fetch("steps").each do |step|
        assert_equal step.fetch("state"), current, "fixture state chain is discontinuous"
        visited << current
        current = transition(current, step.fetch("event"), step.fetch("guards", {}))
        assert_equal step.fetch("target"), current
      end

      visited << current
      assert_equal fixture.fetch("terminal"), current
      fixture.fetch("excludes", []).each { |state| refute_includes visited, state }
      fixture.fetch("includes_once", []).each { |state| assert_equal 1, visited.count(state) }
    end
  end

  def test_unknown_event_is_rejected
    assert_raises(KeyError) { transition("use_run", "invented_event") }
  end

  def test_guarded_event_uses_declared_fallback
    assert_equal "explore_offer", transition("classify", "full_match", "match_satisfies_constraints" => false)
  end

  def test_incomplete_search_is_blocked
    assert_equal "blocked", transition("search", "search_ready", "search_is_complete" => false)
  end

  def test_terminal_states_accept_no_events
    MACHINE.fetch("terminal").each do |state|
      assert_empty MACHINE.dig("states", state).fetch("on", {})
    end
  end

  def test_controller_context_does_not_authorize_ad_hoc_persistence
    assert_includes SKILL_TEXT, "Never serialize Play controller context to an ad hoc file"
    assert_includes SKILL_TEXT, "It does not imply filesystem persistence"
    assert_equal "Play logical controller context", CONTEXT_SCHEMA.fetch("title")
    assert_includes CONTEXT_SCHEMA.fetch("$comment"), "does not define or authorize filesystem persistence"
  end

  def test_execution_visibility_defaults_to_milestones
    assert_includes SKILL_TEXT, "Default user-facing updates to milestone-only"
    assert_includes SKILL_TEXT, "ROTE_FLOW_PROGRESS=0"
    assert_includes SKILL_TEXT, "Tool-call rendering is owned by the host UI"
  end

  def test_quiet_harness_uses_session_scoped_codex_controls
    assert_includes JUSTFILE_TEXT, "harness-quiet:"
    assert_includes START_HARNESS_TEXT, 'model_verbosity="low"'
    assert_includes START_HARNESS_TEXT, 'model_reasoning_summary="none"'
    assert_includes START_HARNESS_TEXT, "hide_agent_reasoning=true"
  end

  def test_update_recipe_verifies_the_source_linked_profile
    assert_match(/update:\n(?:.*\n)*?\s+scripts\/play-profile install\n\s+scripts\/play-profile verify/, JUSTFILE_TEXT)
  end

  def test_every_declared_elicitation_has_selection_and_described_choices
    prompts = YAML.safe_load(
      File.read(File.join(ROOT, "references", "prompts.yaml")), aliases: false
    ).fetch("prompts")
    prompts.each do |name, prompt|
      assert_includes %w[single multiple], prompt.fetch("selection"), name
      assert prompt.fetch("question").strip.end_with?("?"), name
      prompt.fetch("choices").each do |choice|
        assert choice.fetch("label").length.positive?, name
        assert choice.fetch("description").length.positive?, name
      end
    end
  end

  def test_saved_play_is_inspected_before_completed
    successful_index = MACHINE.dig("states", "index", "on", "play_indexed", 0)
    assert_equal "saved_inspect", successful_index.fetch("target")
    assert_equal "inspect_saved_play", MACHINE.dig("states", "saved_inspect", "entry", "action")
    assert_includes SKILL_TEXT, "congratulate the user only after that readback matches"
  end

  def test_first_class_play_commands_cannot_be_decomposed
    actions = YAML.safe_load(
      File.read(File.join(ROOT, "references", "actions.yaml")), aliases: false
    ).fetch("actions")
    assert_equal "use_run", MACHINE.dig("states", "qualify", "on", "exact_play_request", 0, "target")
    assert_equal "run_registry_play", MACHINE.dig("states", "use_run", "entry", "action")
    assert_equal "rote play run <match.reference> <exact-user-parameters> --yes",
                 actions.dig("run_registry_play", "command")
    assert_equal "rote play inspect <publication.canonical_reference> --json",
                 actions.dig("inspect_saved_play", "command")
    assert_match(/A failed\s+`rote play` command is not a capability gap/, SKILL_TEXT)
  end

  def test_unified_search_is_parallel_normalized_and_actionable
    actions = YAML.safe_load(
      File.read(File.join(ROOT, "references", "actions.yaml")), aliases: false
    ).fetch("actions")
    assert_equal "scripts/play-search <request.intent> --json",
                 actions.dig("search_authorized_plays", "command")
    assert_includes PLAY_SEARCH_TEXT, "normalize_query(original)"
    assert_includes PLAY_SEARCH_TEXT, "ThreadPoolExecutor(max_workers=2)"
    assert_includes PLAY_SEARCH_TEXT, "https://play.modiqo.ai/"
    assert_includes PLAY_SEARCH_TEXT, '["rote", "play", "run", exact_reference]'
  end

  def test_management_requests_have_a_read_only_inventory_path
    assert_equal "management_list", MACHINE.dig("states", "qualify", "on", "play_management_request", 0, "target")
    assert_equal "management_offer", MACHINE.dig("states", "qualify", "on", "play_management_choice_required", 0, "target")
    assert_includes SKILL_TEXT, "references/management.md"
  end
end
