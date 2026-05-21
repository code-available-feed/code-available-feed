@status-done
Feature: NFR-004 The Atom XML output is valid RFC 4287 and properly escaped

  All text content that could contain characters reserved in XML ("<", ">",
  "&", '"', "'") is XML-escaped. URL values in href attributes are not
  double-escaped.

  Background:
    Given the environment variable GITHUB_REPOSITORY is "owner/repo"

  Scenario: An ampersand in a title is escaped as "&amp;" in the output
    Given one input article with title "Foo & Bar: A Study"
    When the feed is generated
    Then the raw output bytes contain the substring "Foo &amp; Bar: A Study"
    And the raw output bytes do not contain the substring "Foo & Bar"

  Scenario: A less-than character in a title is escaped as "&lt;" in the output
    Given one input article with title "When N < M: A Counterexample"
    When the feed is generated
    Then the raw output bytes contain the substring "When N &lt; M: A Counterexample"

  Scenario: An ampersand is not double-escaped
    Given one input article with title "Foo & Bar"
    When the feed is generated
    Then the raw output bytes do not contain the substring "&amp;amp;"

  Scenario: An ampersand in a URL is XML-escaped once in href attributes and HTML-then-XML-escaped in content
    Given one input article with abstract URL "https://example.com/path?a=1&b=2"
    And the article has comment URL "https://example.com/path?a=1&b=2"
    When the feed is generated
    Then the raw output bytes contain the substring "https://example.com/path?a=1&amp;b=2"
    And the raw output bytes contain the substring "https://example.com/path?a=1&amp;amp;b=2" inside a content element
    And the raw output bytes do not contain the substring "&amp;amp;amp;b=2"

  Scenario: The generated output is well-formed XML
    Given one input article with title "Foo & <Bar>"
    When the feed is generated
    Then the raw output bytes can be parsed by xml.etree.ElementTree without raising an exception
