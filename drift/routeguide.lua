-- Lua functions and lifecycle hooks available to the Drift test cases.
--
-- Exported functions are callable from testcase expressions using the
-- `${functions:<name>}` syntax, where `functions` is the source name given to
-- this file in routeguide.testcases.yaml.
--
-- During the generation phase a bound function is called with `nil`; during the
-- validation phase it is called with the actual value returned by the provider.

--- Asserts a value is present and non-zero.
--
-- Used by `GetFeature_KnownLocation` to assert that a latitude is returned
-- without pinning the test to one exact coordinate.
local function required(value)
  if value == nil or value == 0 then
    return error("Value must not be empty or zero")
  end
  return value
end

return {
  exported_functions = {
    required = required,
  },

  -- Lifecycle hooks. A real provider would use these to seed and reset state
  -- between operations (for example, by calling a test-only setup endpoint).
  event_handlers = {
    ["operation:started"] = function(event, data)
      -- Set up provider state for the operation about to run.
    end,

    ["operation:finished"] = function(event, data)
      -- Tear down any state created for the operation.
    end,
  },
}
