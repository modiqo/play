# frozen_string_literal: true

require "minitest/autorun"
require "yaml"

ROOT = File.expand_path("..", __dir__)
MACHINE = YAML.safe_load(File.read(File.join(ROOT, "references", "machine.yaml")), aliases: false)
FIXTURES = YAML.safe_load(File.read(File.join(__dir__, "fixtures", "paths.yaml")), aliases: true)

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
    assert_raises(KeyError) { transition("use_preflight", "invented_event") }
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
end
